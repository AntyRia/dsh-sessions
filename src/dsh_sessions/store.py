#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py — DSH (DeepSeek Harness) 本地存储引擎。

DSH 把每个会话存成一条 zstd 压缩的 JSONL（``session.v4.jsonl.zstd``），
索引在 ``storages/workspace.json``，删除的会话进入 ``deleted-sessions``
隔离区（restore-manifest.json）。本模块提供只读扫描与 归档 / 恢复 /
清除 / 孤儿附件回收 等原地操作，与 DSH 自带的隔离区格式互相兼容
（manifest 带 BOM、UTF-8、4 空格缩进，DSH 可识别并恢复）。

目录布局（详见 docs/storage-format.md）::

    <root>/
      sessions/<workspace-dir>/<session-id>/session.v4.jsonl.zstd
      storages/workspace.json
      storages/session_projcache/sessions/<session-id>.json
      deleted-sessions/<YYYYmmdd-HHMMSS>/restore-manifest.json
      attachments/v1/objects/<2hex>/<sha256>

所有操作函数都接收一个 :class:`Root`（或任意路径），不依赖全局状态，
便于多用户目录、测试与库调用。
"""
from __future__ import annotations

import ctypes
import io
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

SESSION_FILE = "session.v4.jsonl.zstd"

try:
    import zstandard
except ImportError:  # 允许未安装时导入本模块（扫描退化为只读目录）
    zstandard = None


# ---------- 根目录 ----------

@dataclass(frozen=True)
class Root:
    """一个 DSH 存储根目录（默认 ``~/.dsh``）。"""

    base: Path

    def __post_init__(self):
        object.__setattr__(self, "base", Path(self.base))

    @property
    def sessions(self) -> Path:
        return self.base / "sessions"

    @property
    def quarantine(self) -> Path:
        return self.base / "deleted-sessions"

    @property
    def projcache(self) -> Path:
        return self.base / "storages" / "session_projcache" / "sessions"

    @property
    def workspace_json(self) -> Path:
        return self.base / "storages" / "workspace.json"

    @property
    def attach_store(self) -> Path:
        return self.base / "attachments" / "v1" / "objects"

    @classmethod
    def of(cls, p) -> "Root":
        """把 Root / Path / str 归一化为 Root。"""
        return p if isinstance(p, Root) else cls(Path(p).expanduser())

    def __str__(self) -> str:  # 方便日志
        return str(self.base)


# ---------- 基础工具 ----------

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def fsize(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def dir_size(p: Path) -> int:
    return sum(fsize(f) for f in p.rglob("*") if f.is_file())


def human(n: float) -> str:
    """字节数 → 人类可读（1.6 MB）。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"  # pragma: no cover


def ftime(ms) -> str:
    """毫秒时间戳 → MM-DD HH:MM（本机时区）。"""
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


def reconfigure_utf8():
    """Windows 控制台输出 UTF-8（尽力而为）。"""
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------- DSH 桌面端状态 / 磁盘 ----------

def desktop_data() -> Path:
    """DSH 桌面端（Electron）数据目录，仅用于 lockfile 探测与占用统计。"""
    env = os.environ.get("DSH_DESKTOP_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "@deepseek-ai" / "dsh-desktop"
    return Path.home() / "AppData" / "Roaming" / "@deepseek-ai" / "dsh-desktop"


def _dsh_process_running() -> bool:
    """按进程名（含 "deepseek"）检测 DSH 桌面端是否在运行（仅 Windows）。"""
    if os.name != "nt":
        return False
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32BasePriority", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snap in (0, -1):
        return False
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        if k32.Process32First(snap, ctypes.byref(pe)):
            while True:
                name = pe.szExeFile.decode("mbcs", "ignore").lower()
                if "deepseek" in name:
                    return True
                if not k32.Process32Next(snap, ctypes.byref(pe)):
                    break
        return False
    finally:
        k32.CloseHandle(snap)


def dsh_running() -> bool:
    """DSH 桌面端在运行：lockfile 5 分钟内更新过，或进程存在。"""
    lf = desktop_data() / "lockfile"
    try:
        if time.time() - lf.stat().st_mtime < 300:
            return True
    except OSError:
        pass
    return _dsh_process_running()


def disk_info(drive: Optional[str] = None) -> Tuple[int, int, int]:
    """(total, avail, free) 字节。

    Windows 用 WinAPI GetDiskFreeSpaceExW —— ``avail`` 才是资源管理器
    显示的可用空间（shutil.disk_usage 在 Windows 上口径不一致）。
    """
    if os.name == "nt":
        drive = drive or "C:\\"

        class _LBU(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

        avail, total, free = _LBU(), _LBU(), _LBU()
        k = ctypes.windll.kernel32
        k.GetDiskFreeSpaceExW.restype = ctypes.c_uint32
        k.GetDiskFreeSpaceExW(drive, ctypes.byref(avail), ctypes.byref(total),
                              ctypes.byref(free))

        def v(b: _LBU) -> int:
            return (b.hi << 32) | b.lo

        return v(total), v(avail), v(free)
    d = shutil.disk_usage(drive or os.path.expanduser("~"))
    return d.total, d.free, d.free


# ---------- 会话读取（实时同步） ----------

def zstd_text(path: Path) -> str:
    """解压 session.v4.jsonl.zstd（多帧 zstd，必须用 stream_reader）。"""
    d = zstandard.ZstdDecompressor()
    return d.stream_reader(io.BytesIO(path.read_bytes())).read().decode("utf-8", "replace")


def parse_session(path: Path) -> dict:
    """解析 session.v4.jsonl.zstd：id / 标题 / 时间 / 来源 / 父会话 / 消息数。"""
    info = {"id": None, "title": None, "created": None, "last": None,
            "origin": None, "parent": None, "user_msgs": 0, "size": fsize(path)}
    if zstandard is None or not path.exists():
        return info
    try:
        text = zstd_text(path)
    except Exception:
        return info
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        t = o.get("type")
        if t == "session":
            info["id"] = o.get("id")
            info["created"] = o.get("createdAt")
            info["origin"] = o.get("origin")
            info["parent"] = o.get("parentSession")
        elif t == "session/title":
            title = (o.get("data") or {}).get("title")
            if title:
                info["title"] = title  # 取最后一次设置的标题
        elif t == "user/message":
            info["user_msgs"] += 1
        tm = o.get("time")
        if tm and (info["last"] is None or tm > info["last"]):
            info["last"] = tm
    if not info["id"]:
        info["id"] = path.parent.name
    info["path"] = str(path.parent)
    return info


def load_index(root: Root) -> dict:
    try:
        return json.loads(root.workspace_json.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"global": {}, "tables": {"workspaces": {}}}


def save_index(root: Root, idx: dict):
    root.workspace_json.parent.mkdir(parents=True, exist_ok=True)
    if root.workspace_json.exists():
        shutil.copy2(root.workspace_json, str(root.workspace_json) + ".bak")
    root.workspace_json.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def workspace_title(idx: dict) -> str:
    ws = idx.get("tables", {}).get("workspaces", {})
    names = [w.get("title") or w.get("path", "?") for w in ws.values()]
    return " / ".join(names) if names else "?"


def iter_session_dirs(root: Root) -> Iterator[Tuple[Path, dict]]:
    """yield (session_dir, info)：遍历所有 workspace 下的会话目录。"""
    if not root.sessions.exists():
        return
    for ws_dir in sorted(p for p in root.sessions.iterdir() if p.is_dir()):
        for sdir in sorted(ws_dir.iterdir()):
            f = sdir / SESSION_FILE
            if sdir.is_dir() and f.exists():
                yield sdir, parse_session(f)


def find_session_dir(root: Root, sid_prefix: str) -> List[Path]:
    hits = []
    for sdir, info in iter_session_dirs(root):
        if info["id"] == sid_prefix or (info["id"] or "").startswith(sid_prefix):
            hits.append(sdir)
    return hits


def resolve_ids(root: Root, ids: List[str], with_subs: bool = False) -> List[Path]:
    """把 id 前缀解析为会话目录列表（可选带上子会话）。歧义/未找到会打印提示。"""
    dirs: List[Path] = []
    for i in ids:
        hits = find_session_dir(root, i)
        if not hits:
            print(f"  未找到: {i}")
        elif len(hits) > 1:
            print(f"  前缀有歧义({len(hits)} 个): {i} -> {[h.name for h in hits]}")
        for h in hits[:1]:
            if h not in dirs:
                dirs.append(h)
    if with_subs:
        parents = {d.name for d in dirs}
        for sdir, info in iter_session_dirs(root):
            if info["parent"] in parents and sdir not in dirs:
                dirs.append(sdir)
    return dirs


def _remove_from_index(root: Root, idset, add: bool = False):
    idx = load_index(root)
    changed = 0
    for wid, w in idx.get("tables", {}).get("workspaces", {}).items():
        for key in ("sessionIds", "archivedSessionIds", "pinnedSessionIds"):
            before = list(w.get(key, []))
            if add:
                w[key] = before + [i for i in sorted(idset) if i not in before]
            else:
                w[key] = [i for i in before if i not in idset]
            if w.get(key) != before:
                changed += 1
    g = idx.setdefault("global", {})
    for key in ("archivedSessionIds", "pinnedSessionIds"):
        before = list(g.get(key, []))
        if add:
            g[key] = before + [i for i in sorted(idset) if i not in before]
        else:
            g[key] = [i for i in before if i not in idset]
    if changed or not add:
        save_index(root, idx)


def _manifest_entry(sid, original, quarantined, cache_original=None, cache_quarantined=None):
    e = {"sessionId": sid, "original": original, "quarantined": quarantined}
    if cache_original:
        e["cacheOriginal"] = cache_original
        e["cacheQuarantined"] = cache_quarantined
    return e


# ---------- 操作 API（CLI 与 GUI 共用） ----------

def scan(root) -> dict:
    """实时扫描 DSH 存储，返回当前全部会话与隔离区状态。

    返回 dict：main / sub（(dir, info) 列表，按最近活动倒序）、
    quarantines（name/path/count/size）、total、ws_ids、arch_ids、
    pinned、ws_title、root（str）。
    """
    root = Root.of(root)
    idx = load_index(root)
    ws_ids, arch_ids, pinned = set(), set(), set()
    for w in idx.get("tables", {}).get("workspaces", {}).values():
        ws_ids.update(w.get("sessionIds", []))
        arch_ids.update(w.get("archivedSessionIds", []))
        pinned.update(w.get("pinnedSessionIds", []))
    g = idx.get("global", {})
    arch_ids.update(g.get("archivedSessionIds", []))
    pinned.update(g.get("pinnedSessionIds", []))

    main_rows, sub_rows = [], []
    for sdir, info in iter_session_dirs(root):
        (sub_rows if info["origin"] == "subagent" else main_rows).append((sdir, info))
    key = lambda r: -(r[1]["last"] or 0)
    main_rows.sort(key=key)
    sub_rows.sort(key=key)

    quarantines = []
    if root.quarantine.exists():
        for q in sorted((p for p in root.quarantine.iterdir() if p.is_dir()),
                        key=lambda p: p.name, reverse=True):
            n = len(list((q / "sessions").glob("*"))) if (q / "sessions").exists() else 0
            quarantines.append({"name": q.name, "path": q, "count": n, "size": dir_size(q)})

    total = (sum(r[1]["size"] for r in main_rows) + sum(r[1]["size"] for r in sub_rows)
             + sum(q["size"] for q in quarantines))
    return {"main": main_rows, "sub": sub_rows, "quarantines": quarantines,
            "total": total, "ws_ids": ws_ids, "arch_ids": arch_ids,
            "pinned": pinned, "ws_title": workspace_title(idx), "root": str(root)}


def op_delete(root, dirs, rm: bool = False) -> Tuple[int, Optional[str]]:
    """删除/归档会话目录列表。返回 (freed_bytes, stamp_or_None)。

    rm=False：移入隔离区（deleted-sessions/<stamp>/，可 restore 恢复）；
    rm=True：永久删除（含投影缓存）。两种模式都会从 workspace.json 索引移除。
    """
    root = Root.of(root)
    idset = {d.name for d in dirs}
    stamp, entries, freed = None, [], 0
    if not rm:
        stamp = now_stamp()
        while (root.quarantine / stamp).exists():
            time.sleep(1.1)
            stamp = now_stamp()
    for sdir in dirs:
        sid = sdir.name
        size = dir_size(sdir)
        freed += size
        cache = root.projcache / f"{sid}.json"
        if rm:
            def _onerror(fn, a, rb):
                try:
                    os.chmod(a, a.stat().st_mode | 0o200)
                    fn(a)
                except OSError:
                    pass
            shutil.rmtree(sdir, onerror=_onerror)
            if cache.exists():
                try:
                    os.chmod(cache, cache.stat().st_mode | 0o200)
                except OSError:
                    pass
                cache.unlink()
                freed += fsize(cache)
        else:
            qsess = root.quarantine / stamp / "sessions" / sid
            qcache = root.quarantine / stamp / "projcache" / f"{sid}.json"
            qsess.parent.mkdir(parents=True, exist_ok=True)
            cache_existed = cache.exists()
            cache_quar = None
            if cache_existed:
                qcache.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cache), str(qcache))
                cache_quar = str(qcache)
            shutil.move(str(sdir), str(qsess))
            entries.append(_manifest_entry(sid, str(sdir), str(qsess),
                                           str(cache) if cache_existed else None, cache_quar))
    if idset:
        _remove_from_index(root, idset)
    if entries:
        (root.quarantine / stamp).mkdir(parents=True, exist_ok=True)
        manifest = root.quarantine / stamp / "restore-manifest.json"
        manifest.write_text("\ufeff" + json.dumps(entries, ensure_ascii=False, indent=4),
                            encoding="utf-8")
        readme = (f"DSH 会话隔离区（由 dsh-sessions 创建，格式与 DSH 一致）\n"
                  f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                  f"恢复：dsh-sessions restore {stamp}\n")
        (root.quarantine / stamp / "README.txt").write_text(readme, encoding="utf-8")
    return freed, stamp


def op_restore(root, stamp: str) -> Tuple[int, int]:
    """从隔离区恢复。返回 (moved, skipped)。恢复后重启 DSH 即可看到。"""
    root = Root.of(root)
    manifest = root.quarantine / stamp / "restore-manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"未找到 {manifest}")
    entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
    moved = skipped = 0
    idset = set()
    for e in entries:
        if Path(e["original"]).exists():
            skipped += 1
            continue
        Path(e["original"]).parent.mkdir(parents=True, exist_ok=True)
        if Path(e["quarantined"]).exists():
            shutil.move(e["quarantined"], e["original"])
            moved += 1
        if e.get("cacheQuarantined") and Path(e["cacheQuarantined"]).exists() \
                and not Path(e.get("cacheOriginal", "x")).exists():
            Path(e["cacheOriginal"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(e["cacheQuarantined"], e["cacheOriginal"])
        idset.add(e["sessionId"])
    if idset:
        _remove_from_index(root, idset, add=True)
    return moved, skipped


def op_purge(root, stamp: Optional[str] = None) -> Tuple[int, List[str]]:
    """永久删除隔离区。stamp: 名称 / 'all' / None=最近一个。返回 (freed, [names])。"""
    root = Root.of(root)
    if not root.quarantine.exists():
        return 0, []
    allq = [p for p in root.quarantine.iterdir() if p.is_dir()]
    if not allq:
        return 0, []
    if stamp == "all":
        qs = allq
    elif stamp is None:
        qs = [max(allq, key=lambda p: p.name)]
    else:
        qs = [root.quarantine / stamp]
        if not qs[0].exists():
            raise FileNotFoundError(f"未找到隔离区 {stamp}")
    total, names = 0, []
    for q in qs:
        total += dir_size(q)
        names.append(q.name)
        shutil.rmtree(q)
    return total, names


def op_reclaim(root, rm: bool = False) -> Tuple[List[Path], int]:
    """孤儿附件（不再被任何会话/隔离区引用）。返回 (orphans[Path], size)；rm=True 时删除。

    附件是 sha256 内容寻址的只读文件（``sha256:<hash>`` 在会话内被引用）；
    删除前会先去掉只读属性。
    """
    root = Root.of(root)
    if not root.attach_store.exists():
        return [], 0
    refs = set()
    for r in (root.sessions, root.quarantine):
        if not r.exists():
            continue
        for f in r.rglob(SESSION_FILE):
            try:
                text = zstd_text(f)
            except Exception:
                continue
            refs.update(re.findall(r"sha256:([0-9a-f]{64})", text))
    orphans = [f for f in root.attach_store.rglob("*") if f.is_file() and f.name not in refs]
    sz = sum(fsize(f) for f in orphans)
    if rm:
        for f in orphans:
            os.chmod(f, f.stat().st_mode | 0o200)  # DSH 把对象设为只读
            f.unlink()
            p = f.parent
            if p.exists() and not list(p.iterdir()):
                os.chmod(p, p.stat().st_mode | 0o200)
                p.rmdir()
    return orphans, sz
