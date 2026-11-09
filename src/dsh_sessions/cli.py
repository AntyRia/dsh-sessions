#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py — dsh-sessions 命令行。

    dsh-sessions [--root PATH] <command>

命令:
  list      实时同步显示全部会话（默认命令）
  space     磁盘占用报告（含所在磁盘剩余空间）
  delete    归档会话（隔离区，可 restore 找回）；--rm 永久删除
  restore   从隔离区恢复会话
  purge     永久删除隔离区（默认最近一个；purge all 删全部）
  reclaim   清理孤儿附件（--rm 真正删除）
  doctor    环境体检：存储根检测、DSH 运行状态、磁盘空间

说明:
  - 存储根默认自动检测（DSH_HOME 环境变量 > 上次选择 > ~/.dsh > 其他用户目录），
    也可用 --root PATH 手动指定。
  - id 支持前缀匹配，例如 delete 0497。
  - 删除/恢复/清理前建议先完全退出 DSH 桌面端，避免文件锁。
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import detect
from . import store as ds
from . import __version__

# ---------- 输出 ----------

def _state_of(info, s):
    if info["id"] in s["pinned"]:
        return "已固定"
    if info["id"] in s["arch_ids"]:
        return "已归档"
    if info["id"] in s["ws_ids"]:
        return "索引内"
    return "索引外"


def _print_rows(rows, s):
    for sdir, info in rows:
        title = (info["title"] or "(无标题)").strip().replace("\n", " ")
        if len(title) > 34:
            title = title[:33] + "…"
        print(f"  {info['id'][-24:]:24s} {title:36s} {ds.ftime(info['created'])}"
              f" -> {ds.ftime(info['last'])}  {ds.human(info['size']):>8s}"
              f"  [{_state_of(info, s)}]")


# ---------- 命令 ----------

def cmd_list(args, det) -> int:
    root = ds.Root.of(det.root)
    if not root.sessions.exists():
        print(f"存储根下没有 sessions/ 目录: {det.root}")
        print("（可运行 dsh-sessions doctor 检查检测情况）")
        return 1
    s = ds.scan(root)
    print(f"DSH 会话（实时同步自 {det.root}）")
    print(f"工作区: {s['ws_title']}")
    total = 0
    if s["main"]:
        print(f"\n主会话（侧栏可见，{len(s['main'])} 个）:")
        _print_rows(s["main"], s)
        total += sum(r[1]["size"] for r in s["main"])
    if s["sub"]:
        print(f"\n隐藏子会话（subagent，侧栏不显示，{len(s['sub'])} 个）:")
        _print_rows(s["sub"], s)
        total += sum(r[1]["size"] for r in s["sub"])
    if s["quarantines"]:
        print(f"\n隔离区 deleted-sessions（{len(s['quarantines'])} 个，可 restore 恢复）:")
        for q in s["quarantines"]:
            print(f"  {q['name']}  {q['count']} 个会话  {ds.human(q['size'])}")
        total += sum(q["size"] for q in s["quarantines"])
    print(f"\n小计: {ds.human(total)}   共 {len(s['main']) + len(s['sub'])} 个活动会话")
    print("提示: dsh-sessions delete <id前缀> [--rm]  |  purge [时间戳]")
    return 0


def cmd_delete(args, det) -> int:
    root = ds.Root.of(det.root)
    ids = [a for a in args.ids if not a.startswith("--")]
    if not ids:
        print("用法: dsh-sessions delete <id前缀...> [--rm] [--subs]")
        return 1
    dirs = ds.resolve_ids(root, ids, with_subs=args.subs)
    if not dirs:
        return 1
    if ds.dsh_running():
        print("提示: DSH 桌面端可能正在运行，建议先退出再删除。")
    if args.rm:
        print("永久删除:")
    else:
        print(f"将归档到 {root.quarantine}（可 restore 恢复）:")
    for d in dirs:
        print(f"  {d.name}  ({ds.human(ds.dir_size(d))})")
    freed, stamp = ds.op_delete(root, dirs, rm=args.rm)
    print(f"完成，释放/移出 {ds.human(freed)}" + (f" -> {stamp}" if stamp else ""))
    return 0


def cmd_restore(args, det) -> int:
    root = ds.Root.of(det.root)
    if not args.stamp:
        qs = [q["name"] for q in ds.scan(root)["quarantines"]]
        print("可用的隔离区:")
        for q in qs or ["(空)"]:
            print("  ", q)
        return 1
    moved, skipped = ds.op_restore(root, args.stamp)
    print(f"从 {args.stamp} 恢复 {moved} 个（跳过 {skipped} 个已存在的），重启 DSH 后即可看到。")
    return 0


def cmd_purge(args, det) -> int:
    root = ds.Root.of(det.root)
    freed, names = ds.op_purge(root, args.stamp)
    if not names:
        print("隔离区为空。")
        return 0
    for n in names:
        print(f"  已删除 {n}")
    print(f"完成，释放 {ds.human(freed)}")
    return 0


def cmd_reclaim(args, det) -> int:
    root = ds.Root.of(det.root)
    orphans, sz = ds.op_reclaim(root, rm=False)
    if not orphans:
        print("没有孤儿附件。")
        return 0
    print(f"孤儿附件: {len(orphans)} 个, 共 {ds.human(sz)}")
    for f in orphans[:10]:
        print(f"   {f.parent.name}/{f.name}")
    if len(orphans) > 10:
        print(f"   ... 其余 {len(orphans) - 10} 个")
    if args.rm:
        ds.op_reclaim(root, rm=True)
        print(f"已删除，释放 {ds.human(sz)}")
    else:
        print("（加 --rm 真正删除）")
    return 0


def cmd_space(args, det) -> int:
    root = ds.Root.of(det.root)
    print(f"DSH 磁盘占用（{det.root} 及桌面端数据）:")
    dd = ds.desktop_data()
    for name, p in (("会话 sessions/", root.sessions),
                    ("隔离区 deleted-sessions/", root.quarantine),
                    ("附件 attachments/", root.base / "attachments"),
                    ("运行时 dsh-runtimes/", root.base / "dsh-runtimes"),
                    ("缓存 cache/", root.base / "cache"),
                    ("桌面端数据 (Roaming)", dd)):
        if p.exists():
            print(f"  {name:28s} {ds.human(ds.dir_size(p)):>10s}")
    print(f"  {'合计':28s} {ds.human(ds.dir_size(root.base) + (ds.dir_size(dd) if dd.exists() else 0)):>10s}")
    try:
        total, avail, _ = ds.disk_info(root.base.anchor or None)
        print(f"磁盘 {root.base.anchor or '~'}: 总 {ds.human(total)}  可用 {ds.human(avail)}  已用 {ds.human(total - avail)}")
    except Exception:
        pass
    return 0


def cmd_doctor(args, det) -> int:
    print(f"dsh-sessions {__version__} 环境检查")
    print(f"  Python:   {sys.version.split()[0]}")
    import dsh_sessions.store as _s
    print(f"  zstandard: {'OK' if _s.zstandard else '缺失（pip install zstandard）'}")
    print(f"  DSH 桌面端: {'运行中' if ds.dsh_running() else '未运行'}")

    print("\n  候选存储根（按优先级）:")
    for c in detect.candidates():
        mark = "✓" if c.valid else "✗"
        print(f"    {mark} [{c.source}] {c.root}  {c.reason}")
    print(f"\n  当前使用: {det.root}（{det.source}，{det.reason}）")

    root = ds.Root.of(det.root)
    if root.sessions.exists():
        s = ds.scan(root)
        print(f"  会话: 主 {len(s['main'])} + 子 {len(s['sub'])}，"
              f"隔离区 {len(s['quarantines'])}，合计 {ds.human(s['total'])}")
    dd = ds.desktop_data()
    if dd.exists():
        print(f"  桌面端数据: {dd}（{ds.human(ds.dir_size(dd))}）")
    try:
        total, avail, _ = ds.disk_info(root.base.anchor or None)
        print(f"  磁盘 {root.base.anchor or '~'}: 总 {ds.human(total)}  可用 {ds.human(avail)}")
    except Exception:
        pass
    return 0


CMDS = ("list", "space", "delete", "restore", "purge", "reclaim", "doctor")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="dsh-sessions",
        description="DeepSeek Harness (DSH) 会话管理：实时同步、归档/删除、隔离区、孤儿附件回收。",
    )
    ap.add_argument("--version", action="version", version=f"dsh-sessions {__version__}")
    ap.add_argument("--root", metavar="PATH", dest="root",
                    help="DSH 存储根目录（默认自动检测；环境变量 DSH_HOME 优先级更高）")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list", help="实时同步显示全部会话（默认）")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("space", help="磁盘占用报告")
    p.set_defaults(fn=cmd_space)
    p = sub.add_parser("delete", help="归档/删除会话")
    p.add_argument("ids", nargs="*", help="会话 id 或前缀")
    p.add_argument("--rm", action="store_true", help="永久删除（默认归档到隔离区）")
    p.add_argument("--subs", action="store_true", help="连同子会话 (subagent) 一起处理")
    p.set_defaults(fn=cmd_delete)
    p = sub.add_parser("restore", help="从隔离区恢复会话")
    p.add_argument("stamp", nargs="?", help="隔离区时间戳（缺省列出可用项）")
    p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("purge", help="永久删除隔离区")
    p.add_argument("stamp", nargs="?", help="隔离区时间戳 / all（缺省=最近一个）")
    p.set_defaults(fn=cmd_purge)
    p = sub.add_parser("reclaim", help="清理孤儿附件")
    p.add_argument("--rm", action="store_true", help="真正删除（缺省只列出）")
    p.set_defaults(fn=cmd_reclaim)
    p = sub.add_parser("doctor", help="环境体检")
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ds.reconfigure_utf8()
    ap = build_parser()
    args = ap.parse_args(argv)
    if not hasattr(args, "fn"):
        args = argparse.Namespace(cmd="list", root=getattr(args, "root", None), fn=cmd_list)
    det = detect.resolve(args.root)
    if det.source == detect.SRC_MANUAL:
        print(f"存储根: {det.root}（手动指定）{'' if det.reason.startswith('有效') else '  ' + det.reason}")
    elif det.source not in (detect.SRC_DEFAULT,):
        print(f"存储根: {det.root}（{det.source}）")
    return args.fn(args, det)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
