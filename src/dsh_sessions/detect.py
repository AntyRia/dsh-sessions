#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect.py — DSH 存储根目录的自动检测与配置持久化。

检测优先级（取第一个有效目录）：

1. 环境变量 ``DSH_HOME``（最高，显式覆盖）
2. 上次保存的选择（config.json 中的 ``dsh_root``）
3. 当前用户默认目录 ``~/.dsh``
4. 其他本地用户目录的 ``<user>/.dsh``（仅 Windows，自动检测兜底）

有效性判定：目录存在，且包含 ``sessions/`` 子目录或
``storages/workspace.json`` 索引（二者有一即可）。

配置目录：Windows ``%APPDATA%/dsh-sessions``，
其他平台 ``$XDG_CONFIG_HOME/dsh-sessions``（默认 ``~/.config/dsh-sessions``）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

APP_DIR_NAME = "dsh-sessions"

# 候选来源标记（GUI/CLI 展示用）
SRC_ENV = "DSH_HOME"
SRC_CONFIG = "上次选择"
SRC_DEFAULT = "默认"
SRC_SCAN = "自动检测"
SRC_MANUAL = "手动指定"


@dataclass(frozen=True)
class Candidate:
    """一个候选 DSH 存储根目录及其检测结论。"""

    root: Path
    source: str
    valid: bool
    reason: str

    def __str__(self) -> str:
        return f"[{self.source}] {self.root}  {'✓ ' if self.valid else '✗ '}{self.reason}"


@dataclass(frozen=True)
class Detected:
    """解析出的实际使用根目录（detect() / resolve() 的返回值）。"""

    root: Path
    source: str
    reason: str


# ---------- 配置持久化 ----------

def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / APP_DIR_NAME


def load_config() -> dict:
    try:
        return json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    """保存配置（dsh_root / auto_refresh 等），尽力而为、不抛异常。"""
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / "config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------- 有效性判定 ----------

def is_valid_root(p) -> Tuple[bool, str]:
    """目录是否像一个 DSH 存储根：需含 sessions/ 或 storages/workspace.json。"""
    p = Path(p)
    if not p.is_dir():
        return False, "目录不存在"
    if (p / "sessions").is_dir():
        return True, "有效（含 sessions/）"
    if (p / "storages" / "workspace.json").is_file():
        return True, "有效（含 storages/workspace.json）"
    return False, "未找到 sessions/ 或 storages/workspace.json"


def default_home_root() -> Path:
    return Path.home() / ".dsh"


# ---------- 候选枚举与检测 ----------

def candidates() -> List[Candidate]:
    """按优先级列出全部候选根目录（含有效性判定）。"""
    seen = set()
    out: List[Candidate] = []

    def add(p: Path, source: str):
        p = Path(p).expanduser()
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        ok, reason = is_valid_root(p)
        out.append(Candidate(root=p, source=source, valid=ok, reason=reason))

    env = os.environ.get("DSH_HOME")
    if env:
        add(Path(env), SRC_ENV)

    cfg = load_config()
    if cfg.get("dsh_root"):
        add(Path(cfg["dsh_root"]), SRC_CONFIG)

    add(default_home_root(), SRC_DEFAULT)

    if os.name == "nt":  # 其他本地用户目录兜底（C:\Users\<user>\.dsh）
        home = Path.home()
        users = home.parent
        skip = {"all users", "default", "default user", "public", "desktop.ini"}
        try:
            for u in sorted(users.iterdir(), key=lambda p: p.name.lower()):
                if u.is_dir() and u.name.lower() not in skip \
                        and u.name.lower() != home.name.lower():
                    add(u / ".dsh", SRC_SCAN)
        except OSError:
            pass
    return out


def detect() -> Optional[Detected]:
    """自动检测：返回第一个有效候选；找不到返回 None。"""
    for c in candidates():
        if c.valid:
            return Detected(root=c.root, source=c.source, reason=c.reason)
    return None


def resolve(explicit=None) -> Detected:
    """解析最终使用的根目录：显式参数 > 自动检测 > 默认目录。

    显式路径即使无效也会返回（source=手动指定，reason 说明原因），
    由调用方决定是否提示。
    """
    if explicit is not None:
        p = Path(str(explicit)).expanduser()
        ok, reason = is_valid_root(p)
        return Detected(root=p, source=SRC_MANUAL, reason=reason)
    d = detect()
    if d:
        return d
    return Detected(root=default_home_root(), source=SRC_DEFAULT,
                    reason="未检测到有效 DSH 存储")
