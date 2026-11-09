# -*- coding: utf-8 -*-
"""detect 模块：候选优先级、有效性判定、resolve 行为。"""
import json

import pytest

import dsh_sessions.detect as detect


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Path.home -> tmp_path；envroot 与默认 ~/.dsh 都是有效 DSH 根。"""
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "envroot"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(detect.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "envroot" / "sessions").mkdir(parents=True)
    (tmp_path / ".dsh" / "sessions").mkdir(parents=True)
    return tmp_path


def test_is_valid_root(tmp_path):
    p = tmp_path / "r"
    assert detect.is_valid_root(p) == (False, "目录不存在")
    (p / "sessions").mkdir(parents=True)
    ok, _ = detect.is_valid_root(p)
    assert ok
    q = tmp_path / "q" / "storages"
    q.mkdir(parents=True)
    (q / "workspace.json").write_text("{}", encoding="utf-8")
    ok, _ = detect.is_valid_root(q.parent)
    assert ok


def test_candidates_priority(home):
    cands = detect.candidates()
    assert cands[0].source == detect.SRC_ENV
    assert cands[0].root == home / "envroot" and cands[0].valid
    srcs = [c.source for c in cands]
    assert detect.SRC_DEFAULT in srcs
    assert srcs.index(detect.SRC_ENV) < srcs.index(detect.SRC_DEFAULT)
    # 默认根有效
    default = next(c for c in cands if c.source == detect.SRC_DEFAULT)
    assert default.valid


def test_candidates_config_between_env_and_default(home):
    (home / "cfgroot" / "sessions").mkdir(parents=True)
    detect.save_config({"dsh_root": str(home / "cfgroot")})
    cands = detect.candidates()
    srcs = [c.source for c in cands]
    # 顺序：DSH_HOME > 上次选择 > 默认（其后可能还有其他用户目录兜底）
    assert srcs[:3] == [detect.SRC_ENV, detect.SRC_CONFIG, detect.SRC_DEFAULT]
    assert cands[1].valid


def test_detect_picks_env_first(home):
    d = detect.detect()
    assert d.root == home / "envroot" and d.source == detect.SRC_ENV


def test_detect_falls_back_to_default(home):
    (home / "envroot" / "sessions").rmdir()
    d = detect.detect()
    assert d.root == home / ".dsh" and d.source == detect.SRC_DEFAULT


def test_detect_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "envroot"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(detect.Path, "home", classmethod(lambda cls: tmp_path / "me"))
    monkeypatch.setattr(detect.os, "name", "nt")
    (tmp_path / "envroot").mkdir()              # 存在但无 sessions/ → 无效
    (tmp_path / "me" / ".dsh").mkdir(parents=True)  # 存在但空 → 无效
    assert detect.detect() is None
    # resolve 仍返回默认根（带说明）
    d = detect.resolve()
    assert d.root == tmp_path / "me" / ".dsh" and d.source == detect.SRC_DEFAULT


def test_resolve_explicit(home):
    d = detect.resolve(home / ".dsh")
    assert d.source == detect.SRC_MANUAL and d.root == home / ".dsh"
    d2 = detect.resolve(str(home / "nope"))
    assert d2.source == detect.SRC_MANUAL and "不存在" in d2.reason


def test_config_roundtrip(home):
    detect.save_config({"dsh_root": "x", "auto_refresh": False})
    cfg = detect.load_config()
    assert cfg == {"dsh_root": "x", "auto_refresh": False}


def test_scan_other_user_homes(tmp_path, monkeypatch):
    """Windows 下其他用户目录的 .dsh 应作为兜底候选。"""
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "envroot"))
    monkeypatch.setattr(detect.Path, "home", classmethod(lambda cls: tmp_path / "Users" / "me"))
    monkeypatch.setattr(detect.os, "name", "nt")
    (tmp_path / "Users" / "me" / ".dsh" / "sessions").mkdir(parents=True)
    (tmp_path / "Users" / "you" / ".dsh" / "sessions").mkdir(parents=True)
    (tmp_path / "Users" / "Public").mkdir(parents=True)
    cands = detect.candidates()
    assert any(c.source == detect.SRC_SCAN and c.root == tmp_path / "Users" / "you" / ".dsh"
               for c in cands)
    assert not any(c.root.name == "Public" for c in cands)
