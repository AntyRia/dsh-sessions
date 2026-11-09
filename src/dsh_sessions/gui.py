#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py — dsh-sessions tkinter 桌面端（浅色主题）。

数据实时读取自 DSH 存储（默认自动检测，也可手动选择路径），与 DSH 保持同步。
左侧：会话（主会话 / 隐藏子会话），可归档、永久删除。
右侧：隔离区（deleted-sessions），可恢复、清除。
顶部：存储根路径 + 自动检测 / 手动选择。
底部：状态栏（DSH 运行状态 / 会话统计 / 磁盘用量 / 悬停行详情 / 操作回执）。
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

from . import detect
from . import store as ds
from . import __version__

try:  # 高 DPI
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ---- 色板（Catppuccin Latte 浅色 + 校验过的状态色）----
# 深色备用（Mocha）: BG #1e1e2e PANEL #181825 ZEBRA #1d1d2c GRIDLINE #2a2a3a
#   FG #cdd6f4 MUTED #9aa0b8 FAINT #6c7086 ACCENT #89b4fa BTN #45475a
#   BTN_HOVER #585b70 SEL #313244 GREEN #0ca30c AMBER #fab219 RED #d03b3b
BG = "#eff1f5"        # 页面底
PANEL = "#ffffff"     # 表格表面（白）
ZEBRA = "#f4f6fa"     # 隔行（比表面深一档）
GRIDLINE = "#dce0e8"  # 发丝线
FG = "#4c4f69"        # 主文本
MUTED = "#6c6f85"     # 次级文本
FAINT = "#949cab"     # 占位/弱提示
ACCENT = "#1e66f5"    # 强调（选中/按钮）
BTN = "#e6e9ef"       # 按钮底
BTN_HOVER = "#dce0e8"
SEL = "#cddcf7"       # 选中行
GREEN = "#40a02b"     # 状态：好
AMBER = "#df8e1d"     # 状态：警告
RED = "#d25252"       # 状态：危险

FONT = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 9, "bold")
FONT_T = ("Microsoft YaHei UI", 11, "bold")
SMALL = ("Microsoft YaHei UI", 8)
MONO = ("Consolas", 9)
MONO_S = ("Consolas", 8)


def short_id(sid: str) -> str:
    if sid.startswith("session-"):
        return "…" + sid[-16:]
    return sid[:12] + "…"


def pretty_path(p: Path) -> str:
    """~/.dsh 形式的路径展示。"""
    home = Path.home()
    p = Path(p)
    try:
        if p == home or home in p.parents:
            return "~/" + "/".join(p.relative_to(home).parts)
    except ValueError:
        pass
    return str(p)


def _drive_label(root: Path) -> str:
    if os.name == "nt" and root.anchor:
        return root.anchor.rstrip("\\") + "盘"
    return "磁盘"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.msg = ""
        cfg = detect.load_config()
        self.auto = cfg.get("auto_refresh", True)
        self._snap_prev = None
        self._hover_iid = None
        self._after_id = None
        self._sb_cells = []

        self.detected = detect.resolve()
        self.root_path = self.detected.root
        self.root_source = self.detected.source

        root.title("DSH 会话管理")
        root.configure(bg=BG)
        w, h = 1020, 660
        root.update_idletasks()
        x = max(0, (root.winfo_screenwidth() - w) // 2)
        y = max(0, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(880, 540)
        root.after(120, self._init_window)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=GRIDLINE, foreground=MUTED,
                        font=SMALL, relief="flat", padding=(6, 4))
        style.map("Treeview", background=[("selected", SEL)],
                  foreground=[("selected", ACCENT)])
        style.map("Treeview.Heading", background=[("active", BTN)])

        self._build_topbar()
        self._build_pane()
        self._build_statusbar()
        root.bind("<F5>", lambda e: self.refresh())
        root.bind("<Control-f>", lambda e: self._focus_filter())
        root.bind("<Control-F>", lambda e: self._focus_filter())
        self.refresh()
        self._tick()

    # ---------- 小部件 ----------

    def _btn(self, parent, text, cmd, color=FG, base=BTN):
        b = tk.Button(parent, text=text, command=cmd, font=FONT_B,
                      bg=base, fg=color, activebackground=BTN_HOVER, activeforeground=color,
                      relief="flat", bd=0, padx=12, pady=5, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=BTN_HOVER))
        b.bind("<Leave>", lambda e: b.config(bg=base))
        return b

    # ---------- 布局 ----------

    def _build_topbar(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="DSH 会话管理", font=FONT_T, bg=BG, fg=FG).pack(side="left")
        tk.Label(top, text=f"v{__version__}", font=SMALL, bg=BG, fg=FAINT).pack(
            side="left", padx=(8, 0), pady=(8, 0))

        self._btn(top, "刷新", self.refresh, ACCENT).pack(side="right")
        self.var_auto = tk.BooleanVar(value=self.auto)
        tk.Checkbutton(top, text="自动刷新", variable=self.var_auto, command=self.toggle_auto,
                       font=FONT, bg=BG, fg=MUTED, activebackground=BG,
                       activeforeground=MUTED, selectcolor=PANEL, padx=8).pack(
            side="right", padx=(0, 10))
        self.ent_filter = tk.Entry(top, font=FONT, bg=PANEL, fg=FG, insertbackground=FG,
                                   relief="flat", width=18)
        self.ent_filter.pack(side="right", padx=(0, 10))
        self._set_ph()
        self.ent_filter.bind("<KeyRelease>", lambda e: self._apply_filter())
        self.ent_filter.bind("<FocusIn>", self._ph_focus)
        self.ent_filter.bind("<FocusOut>", self._ph_blur)
        self.ent_filter.bind("<Escape>", lambda e: self._filter_clear())

        # 存储根路径行（自动检测 / 手动选择）
        pbar = tk.Frame(self.root, bg=BG)
        pbar.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(pbar, text="DSH 存储", font=SMALL, bg=BG, fg=MUTED).pack(side="left", padx=(0, 8))
        self.lb_path = tk.Label(pbar, text="", font=MONO_S, bg=BG, fg=MUTED)
        self.lb_path.pack(side="left")
        self.lb_src = tk.Label(pbar, text="", font=SMALL, bg=BG, fg=FAINT)
        self.lb_src.pack(side="left", padx=(8, 0))
        self._btn(pbar, "回收孤儿附件", self.do_reclaim, MUTED).pack(side="right", padx=(0, 6))
        self._btn(pbar, "选择路径…", self.do_browse, MUTED).pack(side="right", padx=(0, 6))
        self._btn(pbar, "自动检测", self.do_detect, MUTED).pack(side="right")
        self._sync_pathbar()

        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x", padx=12)

    def _sync_pathbar(self):
        self.lb_path.config(text=pretty_path(self.root_path))
        ok, reason = detect.is_valid_root(self.root_path)
        self.lb_src.config(text=f"{self.root_source} · {reason}")

    # ---------- 过滤框 ----------

    def _filter_clear(self, _e=None):
        self.ent_filter.delete(0, "end")
        self._apply_filter()
        self._set_ph()

    def _focus_filter(self, _e=None):
        self.ent_filter.focus_set()

    def _set_ph(self):
        self.ent_filter.delete(0, "end")
        self.ent_filter.insert(0, "过滤 标题 / ID…")
        self.ent_filter.config(fg=FAINT)

    def _ph_focus(self, _e=None):
        if self.ent_filter.get() == "过滤 标题 / ID…":
            self.ent_filter.delete(0, "end")
            self.ent_filter.config(fg=FG)

    def _ph_blur(self, _e=None):
        if not self.ent_filter.get().strip():
            self._set_ph()

    def _filter_text(self):
        t = self.ent_filter.get().strip()
        return "" if t == "过滤 标题 / ID…" else t

    # ---------- 主面板 ----------

    def _build_pane(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        paned = tk.PanedWindow(body, orient="horizontal", bg=BG)
        paned.pack(fill="both", expand=True)
        self.paned = paned
        paned.add(self._build_sessions_frame(), stretch="always")
        paned.add(self._build_quarantine_frame(), stretch="always")

    def _init_window(self):
        try:
            w = self.paned.winfo_width()
            if w > 200:
                self.paned.sashpos(0, int(w * 0.66))
        except tk.TclError:
            pass
        try:  # 浅色标题栏（Win10 2004+；改深色主题时置 1）
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(self.root.winfo_id()), 20, ctypes.byref(ctypes.c_int(0)), 4)
        except Exception:
            pass

    def _build_sessions_frame(self):
        f = tk.Frame(self.root, bg=BG)
        wrap = tk.Frame(f, bg=GRIDLINE, highlightthickness=1, highlightbackground=GRIDLINE)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, show="headings", selectmode="extended",
                                 columns=("id", "title", "created", "last", "size", "state"))
        for col, text, w, anchor in (
                ("id", "ID", 92, "w"), ("title", "标题", 200, "w"),
                ("created", "创建", 112, "w"), ("last", "最近活动", 112, "w"),
                ("size", "大小", 76, "e"), ("state", "状态", 64, "w")):
            self.tree.column(col, width=w, anchor=anchor, stretch=(col == "title"))
            self.tree.heading(col, text=text)
        self.tree.tag_configure("head", font=FONT_B, foreground=MUTED)
        self.tree.tag_configure("sub", foreground=MUTED)
        self.tree.tag_configure("z1", background=ZEBRA)
        self.tree.tag_configure("ph", foreground=FAINT)
        y = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_selinfo())
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda e: self._on_double())
        self.tree.bind("<Delete>", lambda e: self.do_delete())
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", lambda e: self._set_hover(None))

        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", pady=(8, 2))
        self.lb_sel = tk.Label(bar, text="", font=FONT, bg=BG, fg=MUTED)
        self.lb_sel.pack(side="left")
        self._btn(bar, "复制 ID", self.do_copy, MUTED).pack(side="right")
        self._btn(bar, "永久删除", self.do_delete, RED).pack(side="right", padx=(0, 6))
        self._btn(bar, "归档", self.do_archive, ACCENT).pack(side="right", padx=(0, 6))
        return f

    def _build_quarantine_frame(self):
        f = tk.Frame(self.root, bg=BG)
        wrap = tk.Frame(f, bg=GRIDLINE, highlightthickness=1, highlightbackground=GRIDLINE)
        wrap.pack(fill="both", expand=True)
        self.qtree = ttk.Treeview(wrap, show="headings", selectmode="extended",
                                  columns=("name", "count", "size"))
        for col, text, w in (("name", "隔离区", 150), ("count", "会话数", 72), ("size", "大小", 70)):
            self.qtree.column(col, width=w, anchor="w" if col == "name" else "e")
            self.qtree.heading(col, text=text)
        self.qtree.tag_configure("ph", foreground=FAINT)
        y = ttk.Scrollbar(wrap, orient="vertical", command=self.qtree.yview)
        self.qtree.configure(yscrollcommand=y.set)
        self.qtree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        self.qtree.bind("<<TreeviewSelect>>", lambda e: self._update_qselinfo())
        self.qtree.bind("<Double-1>", self._on_qdouble)

        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", pady=(8, 2))
        self.lb_qsel = tk.Label(bar, text="", font=FONT, bg=BG, fg=MUTED)
        self.lb_qsel.pack(side="left")
        self._btn(bar, "清除", self.do_purge, AMBER).pack(side="right", padx=(0, 6))
        self._btn(bar, "恢复", self.do_restore, GREEN).pack(side="right")
        return f

    # ---------- 状态栏（指标行） ----------

    def _sb_cell(self, parent, label):
        if self._sb_cells:
            tk.Frame(parent, width=1, bg=GRIDLINE, height=18).pack(side="left", fill="y", pady=7)
        cell = tk.Frame(parent, bg=BG)
        cell.pack(side="left")
        tk.Label(cell, text=label, font=SMALL, bg=BG, fg=MUTED).pack(side="left", padx=(10, 5), pady=9)
        val = tk.Label(cell, text="—", font=FONT_B, bg=BG, fg=FG)
        val.pack(side="left", padx=(0, 10), pady=6)
        self._sb_cells.append(cell)
        return val

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=GRIDLINE, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=BG)
        inner.pack(fill="x", padx=4)

        # DSH 运行状态（状态点 + 文字，颜色不单独承载含义）
        c = tk.Frame(inner, bg=BG)
        c.pack(side="left")
        tk.Label(c, text="DSH", font=SMALL, bg=BG, fg=MUTED).pack(side="left", padx=(10, 5), pady=9)
        self.dot = tk.Label(c, text="●", font=SMALL, bg=BG, fg=FAINT)
        self.dot.pack(side="left", padx=(0, 3))
        self.lb_dsh = tk.Label(c, text="—", font=FONT_B, bg=BG, fg=FG)
        self.lb_dsh.pack(side="left", padx=(0, 10), pady=6)
        self._sb_cells.append(c)

        self.val_sessions = self._sb_cell(inner, "会话")
        self.val_quar = self._sb_cell(inner, "隔离区")
        self.val_total = self._sb_cell(inner, "会话总量")

        # 磁盘用量（细条 + 直接标注）
        cd = tk.Frame(inner, bg=BG)
        cd.pack(side="left")
        self.lb_diskname = tk.Label(cd, text=_drive_label(self.root_path),
                                    font=SMALL, bg=BG, fg=MUTED)
        self.lb_diskname.pack(side="left", padx=(10, 6), pady=9)
        self.meter = tk.Canvas(cd, width=120, height=6, bg=BG, highlightthickness=0)
        self.meter.pack(side="left", pady=10)
        self.val_disk = tk.Label(cd, text="—", font=SMALL, bg=BG, fg=FG)
        self.val_disk.pack(side="left", padx=(8, 10))
        self._sb_cells.append(cd)

        self.lb_hover = tk.Label(inner, text="", font=MONO, bg=BG, fg=FAINT, anchor="e")
        self.lb_hover.pack(side="left", fill="x", expand=True, padx=6)
        self.lb_msg = tk.Label(inner, text="", font=FONT_B, bg=BG, fg=ACCENT, anchor="e")
        self.lb_msg.pack(side="right", padx=(0, 6))

    def _set_meter(self, frac):
        c, w, h = self.meter, 120, 6
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=GRIDLINE, width=0)
        if frac <= 0:
            return
        frac = min(1.0, frac)
        fill_w = max(2, int(w * frac))
        color = GREEN if frac < 0.70 else (AMBER if frac < 0.90 else RED)
        c.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

    def _update_statusbar(self):
        d = self.data
        running = ds.dsh_running()
        self.dot.config(fg=GREEN if running else FAINT)
        self.lb_dsh.config(text="运行中" if running else "未运行")
        self.val_sessions.config(text=str(len(d["main"]) + len(d["sub"])))
        self.val_quar.config(text=str(len(d["quarantines"])))
        self.val_total.config(text=ds.human(d["total"]))
        try:
            total, avail, _ = ds.disk_info(self.root_path.anchor or None)
            self._set_meter((total - avail) / total if total else 0)
            self.val_disk.config(text=f"{ds.human(avail)} / {ds.human(total)}")
        except Exception:
            self._set_meter(0)
            self.val_disk.config(text="—")
        self.lb_msg.config(text=self.msg)

    # ---------- 存储根：自动检测 / 手动选择 ----------

    def _save_cfg(self):
        detect.save_config({"dsh_root": str(self.root_path),
                            "auto_refresh": self.var_auto.get()})

    def set_root(self, path, source: str, note: str = ""):
        self.root_path = Path(path).expanduser()
        self.root_source = source
        self._sync_pathbar()
        self.lb_diskname.config(text=_drive_label(self.root_path))
        self.msg = note
        self._snap_prev = None
        self._save_cfg()
        self.refresh(force=True)

    def do_detect(self):
        d = detect.detect()
        if d:
            self.set_root(d.root, d.source,
                          f"自动检测 → {pretty_path(d.root)}（{d.source}）")
            return
        lines = "\n".join(f"  {c.root}\n    {c.reason}" for c in detect.candidates())
        messagebox.showinfo("自动检测", "未找到有效的 DSH 存储目录，请手动选择。\n\n"
                                        "已检查：\n" + lines)

    def do_browse(self):
        p = filedialog.askopeninitialdir(
            title="选择 DSH 存储根目录（包含 sessions/ 的 .dsh 目录）",
            initialdir=str(Path.home()))
        if not p:
            return
        ok, why = detect.is_valid_root(p)
        if not ok and not messagebox.askyesno(
                "路径校验", f"{why}。\n\n仍要使用 {p} 吗？\n（可稍后用「自动检测」找回）"):
            return
        self.set_root(p, detect.SRC_MANUAL, f"已切换 → {pretty_path(p)}（手动选择）")

    # ---------- 数据刷新（数据不变则不动表格，保留选中/滚动） ----------

    @staticmethod
    def _snap(d):
        return (d["ws_title"],
                [(i["id"], i["size"], i["last"], (i["title"] or "")[:40]) for _, i in d["main"]],
                [(i["id"], i["size"], i["last"]) for _, i in d["sub"]],
                [(q["name"], q["size"], q["count"]) for q in d["quarantines"]])

    def refresh(self, force=True):
        root = ds.Root.of(self.root_path)
        try:
            data = ds.scan(root)
        except Exception as e:
            data = {"main": [], "sub": [], "quarantines": [], "total": 0,
                    "ws_ids": set(), "arch_ids": set(), "pinned": set(),
                    "ws_title": f"读取失败: {e}"}
            self.msg = ""
        self.data = data
        self._update_statusbar()
        snap = self._snap(data)
        if force or snap != self._snap_prev:
            self._snap_prev = snap
            self._rebuild(self._filter_text())
            self._update_selinfo()
            self._update_qselinfo()

    def _rebuild(self, q=""):
        d = self.data
        for t in (self.tree, self.qtree):
            t.delete(*t.get_children())
        self.rows = {}
        q = q.strip().lower()
        groups = (("main", "主会话", d["main"]), ("sub", "隐藏子会话 (subagent)", d["sub"]))
        inserted = 0
        for key, label, rows in groups:
            shown = [r for r in rows
                     if not q or q in f"{r[1]['id']} {r[1]['title'] or ''}".lower()]
            if not shown:
                continue
            self.tree.insert("", "end", iid=f"head:{key}",
                             values=(f"{label}（{len(shown)}）", "", "", "", "", ""),
                             tags=("head",))
            for n, (sdir, info) in enumerate(shown):
                sid = info["id"]
                iid = f"sess:{sid}"
                state = self._state(info)
                title = (info["title"] or "(无标题)").strip().replace("\n", " ")
                self.tree.insert("", "end", iid=iid,
                                 values=(short_id(sid), title, ds.ftime(info["created"]),
                                         ds.ftime(info["last"]), ds.human(info["size"]), state),
                                 tags=(["sub"] if info["origin"] == "subagent" else [])
                                 + (["z1"] if n % 2 else []))
                self.rows[iid] = (sdir, info)
                inserted += 1
        if not inserted:
            self.tree.insert("", "end", iid="ph:sess",
                             values=("（无会话）" if q else "（暂无会话）", "", "", "", "", ""),
                             tags=("ph",))
        for qi in d["quarantines"]:
            self.qtree.insert("", "end", values=(qi["name"], qi["count"], ds.human(qi["size"])))
        if not d["quarantines"]:
            self.qtree.insert("", "end", iid="ph:quar", values=("（空）", "", ""), tags=("ph",))

    def _state(self, info):
        d = self.data
        if info["id"] in d["pinned"]:
            return "已固定"
        if info["id"] in d["arch_ids"]:
            return "已归档"
        if info["id"] in d["ws_ids"]:
            return "索引内"
        return "索引外"

    def _apply_filter(self, _e=None):
        self.refresh(force=True)

    def _selected(self):
        """返回 [(dir, info)]；选到分组头则展开为整组"""
        dirs, infos = [], []
        for iid in self.tree.selection():
            if iid in self.rows:
                sdir, info = self.rows[iid]
                dirs.append(sdir)
                infos.append(info)
            elif iid == "head:main":
                for sdir, info in self.data["main"]:
                    dirs.append(sdir)
                    infos.append(info)
            elif iid == "head:sub":
                for sdir, info in self.data["sub"]:
                    dirs.append(sdir)
                    infos.append(info)
        seen, out = set(), []
        for sdir, info in zip(dirs, infos):
            if sdir not in seen:
                seen.add(sdir)
                out.append((sdir, info))
        return out

    def _update_selinfo(self):
        sel = self._selected()
        n = len(sel)
        sz = sum(i["size"] for _, i in sel)
        self.lb_sel.config(text=f"已选 {n} 个会话 / {ds.human(sz)}" if n
                           else "未选择（Ctrl 多选，点分组标题=整组，Del=删除）")

    def _update_qselinfo(self):
        qs = [i for i in self.qtree.selection() if not i.startswith("ph:")]
        self.lb_qsel.config(text=f"已选 {len(qs)} 个隔离区" if qs else "")

    # ---------- 悬停层 ----------

    def _on_motion(self, e):
        iid = self.tree.identify_row(e.y)
        if iid != self._hover_iid:
            self._hover_iid = iid
            self._set_hover(iid)

    def _set_hover(self, iid):
        self._hover_iid = iid
        if iid in self.rows:
            info = self.rows[iid][1]
            self.lb_hover.config(text=info["id"])
        else:
            self.lb_hover.config(text="")

    # ---------- 操作 ----------

    @staticmethod
    def _list_titles(infos, limit=6):
        lines = []
        for info in infos[:limit]:
            t = (info["title"] or "(无标题)").strip().replace("\n", " ")
            lines.append(f"  - {t[:40]}  [{info['id'][-12:]}]")
        if len(infos) > limit:
            lines.append(f"  ... 其余 {len(infos) - limit} 个")
        return "\n".join(lines)

    def _guard_running(self):
        if ds.dsh_running():
            return messagebox.askyesno("DSH 正在运行", "DSH 桌面端可能正在运行。\n"
                                        "建议先完全退出再操作，以免文件锁/索引不一致。\n\n仍然继续？")
        return True

    def do_archive(self, _e=None):
        sel = self._selected()
        if not sel:
            return
        sz = sum(i["size"] for _, i in sel)
        if not messagebox.askyesno("归档会话",
                                   f"将 {len(sel)} 个会话（{ds.human(sz)}）移入隔离区，可稍后恢复：\n\n"
                                   f"{self._list_titles([i for _, i in sel])}"):
            return
        if not self._guard_running():
            return
        try:
            _, stamp = ds.op_delete(ds.Root.of(self.root_path), [d for d, _ in sel], rm=False)
            self.msg = f"已归档 {len(sel)} 个 → {stamp}"
        except Exception as e:
            self.msg = ""
            messagebox.showerror("归档失败", str(e))
            return
        self.refresh()

    def do_delete(self, _e=None):
        sel = self._selected()
        if not sel:
            return
        sz = sum(i["size"] for _, i in sel)
        if not messagebox.askyesno("永久删除",
                                   f"将永久删除 {len(sel)} 个会话（{ds.human(sz)}），不可恢复：\n\n"
                                   f"{self._list_titles([i for _, i in sel])}",
                                   icon="question"):
            return
        if not self._guard_running():
            return
        try:
            freed, _ = ds.op_delete(ds.Root.of(self.root_path), [d for d, _ in sel], rm=True)
            self.msg = f"已删除 {len(sel)} 个，释放 {ds.human(freed)}"
        except Exception as e:
            self.msg = ""
            messagebox.showerror("删除失败", str(e))
            return
        self.refresh()

    def do_copy(self, _e=None):
        sel = self._selected()
        if not sel:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(i["id"] for _, i in sel))
        self.msg = f"已复制 {len(sel)} 个会话 ID"
        self._update_statusbar()

    def do_restore(self, _e=None):
        qs = [i for i in self.qtree.selection() if not i.startswith("ph:")]
        if not qs:
            return
        if not messagebox.askyesno("恢复", f"从隔离区恢复 {len(qs)} 组会话？\n"
                                           "（建议先退出 DSH，恢复后重启 DSH 可见）"):
            return
        if not self._guard_running():
            return
        for iid in qs:
            name = self.qtree.item(iid, "values")[0]
            try:
                moved, skipped = ds.op_restore(ds.Root.of(self.root_path), name)
                self.msg = f"已恢复 {name}: {moved} 个（跳过 {skipped}）"
            except Exception as e:
                self.msg = ""
                messagebox.showerror("恢复失败", str(e))
        self.refresh()

    def do_purge(self, _e=None):
        qs = [i for i in self.qtree.selection() if not i.startswith("ph:")]
        if not qs:
            return
        detail = "\n".join(
            f"  {v[0]}  {v[1]} 个会话  {v[2]}" for v in (self.qtree.item(i, "values") for i in qs))
        if not messagebox.askyesno("清除隔离区",
                                   f"将永久删除 {len(qs)} 个隔离区，不可恢复？\n\n{detail}"):
            return
        if not self._guard_running():
            return
        total = 0
        for iid in qs:
            name = self.qtree.item(iid, "values")[0]
            try:
                freed, _ = ds.op_purge(ds.Root.of(self.root_path), name)
                total += freed
            except Exception as e:
                self.msg = ""
                messagebox.showerror("清除失败", str(e))
        self.msg = f"已清除，释放 {ds.human(total)}"
        self.refresh()

    def do_reclaim(self, _e=None):
        orphans, sz = ds.op_reclaim(ds.Root.of(self.root_path), rm=False)
        if not orphans:
            messagebox.showinfo("回收孤儿附件", "没有孤儿附件。")
            return
        if not messagebox.askyesno("回收孤儿附件",
                                   f"发现 {len(orphans)} 个不再被任何会话引用的附件对象，共 {ds.human(sz)}。\n"
                                   f"删除后不可恢复？"):
            return
        if not self._guard_running():
            return
        try:
            ds.op_reclaim(ds.Root.of(self.root_path), rm=True)
            self.msg = f"已回收 {len(orphans)} 个孤儿附件，释放 {ds.human(sz)}"
        except Exception as e:
            self.msg = ""
            messagebox.showerror("回收失败", str(e))
            return
        self.refresh()

    # ---------- 详情 ----------

    def _on_double(self, _e=None):
        sel = self.tree.selection()
        if len(sel) != 1 or sel[0] not in self.rows:
            return
        sdir, info = self.rows[sel[0]]
        self._show_detail(sdir, info)

    def _on_qdouble(self, _e=None):
        sel = [i for i in self.qtree.selection() if not i.startswith("ph:")]
        if len(sel) != 1:
            return
        name = self.qtree.item(sel[0], "values")[0]
        qdir = ds.Root.of(self.root_path).quarantine / name
        manifest = qdir / "restore-manifest.json"
        lines = [f"隔离区: {name}", f"路径: {qdir}", ""]
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
            lines.append(f"会话数: {len(entries)}")
            for e in entries[:100]:
                lines.append(f"  {e['sessionId']}")
        except Exception:
            lines.append("（无 manifest）")
        top = tk.Toplevel(self.root)
        top.title("隔离区详情")
        top.configure(bg=BG)
        top.geometry("520x440")
        tk.Label(top, text="隔离区详情（恢复/清除用右侧按钮）",
                 font=FONT_B, bg=BG, fg=FG).pack(anchor="w", padx=10, pady=(10, 6))
        txt = tk.Text(top, font=MONO, bg=PANEL, fg=FG, relief="flat", wrap="none", padx=10, pady=8)
        sb = ttk.Scrollbar(top, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 6), pady=(0, 6))
        txt.pack(fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")
        bbar = tk.Frame(top, bg=BG)
        bbar.pack(fill="x", padx=6, pady=(0, 8))
        self._btn(bbar, "关闭", lambda: top.destroy(), ACCENT).pack()

    def _show_detail(self, sdir, info):
        top = tk.Toplevel(self.root)
        top.title("会话详情")
        top.configure(bg=BG)
        top.geometry("560x400")
        top.minsize(480, 320)
        tk.Label(top, text="会话详情", font=FONT_T, bg=BG, fg=FG).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Frame(top, bg=GRIDLINE, height=1).pack(fill="x", padx=14, pady=(4, 6))
        rows = (
            ("会话 ID", info["id"]),
            ("标题", info["title"] or "(无标题)"),
            ("类型", "子会话 (subagent)" if info["origin"] == "subagent" else "主会话"),
            ("父会话", info["parent"] or "-"),
            ("创建", ds.ftime(info["created"])),
            ("最近活动", ds.ftime(info["last"])),
            ("用户消息数", info["user_msgs"]),
            ("大小", ds.human(info["size"])),
            ("状态", self._state(info)),
            ("路径", info.get("path", str(sdir))),
        )
        f = tk.Frame(top, bg=BG)
        f.pack(fill="both", expand=True, padx=14)
        for i, (k, v) in enumerate(rows):
            tk.Label(f, text=k, font=SMALL, bg=BG, fg=MUTED, anchor="w").grid(
                row=i, column=0, sticky="w", pady=4, padx=(2, 10))
            lbl = tk.Label(f, text=str(v), font=MONO if k in ("会话 ID", "路径") else FONT,
                           bg=BG, fg=FG, anchor="w", justify="left")
            lbl.grid(row=i, column=1, sticky="we", pady=4)
        f.columnconfigure(1, weight=1)
        bbar = tk.Frame(top, bg=BG)
        bbar.pack(fill="x", padx=14, pady=(0, 12))
        self._btn(bbar, "复制 ID", lambda: (top.clipboard_clear(),
                                            top.clipboard_append(info["id"])), MUTED).pack(side="left")
        self._btn(bbar, "复制标题", lambda: (top.clipboard_clear(),
                                             top.clipboard_append(info["title"] or "")), MUTED).pack(side="left", padx=(6, 0))
        self._btn(bbar, "关闭", lambda: top.destroy(), ACCENT).pack(side="right")

    # ---------- 自动刷新 ----------

    def toggle_auto(self):
        self.auto = self.var_auto.get()
        self._save_cfg()
        self._cancel_tick()
        self._tick()

    def _cancel_tick(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self):
        self._cancel_tick()
        if self.auto:
            self._after_id = self.root.after(5000, self._tick_once)

    def _tick_once(self):
        self.refresh(force=False)
        self._tick()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
