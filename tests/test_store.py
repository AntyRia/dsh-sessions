# -*- coding: utf-8 -*-
"""store 模块：解析、扫描、归档/恢复、清除、孤儿附件回收。"""
import json

from helpers import make_session, make_workspace_json
from dsh_sessions import store as ds

A = "a" * 64  # 附件 hash
B = "b" * 64


def test_parse_session(tmp_path):
    d = make_session(tmp_path, "WS-x", "session-abc123", title="你好",
                     user_msgs=3, created=1_700_000_000_000)
    info = ds.parse_session(d / ds.SESSION_FILE)
    assert info["id"] == "session-abc123"
    assert info["title"] == "你好"
    assert info["user_msgs"] == 3
    assert info["created"] == 1_700_000_000_000
    assert info["origin"] is None
    assert info["size"] > 0


def test_parse_session_subagent(tmp_path):
    d = make_session(tmp_path, "WS-x", "sub-0497", title=None, origin="subagent",
                     parent="session-abc123")
    info = ds.parse_session(d / ds.SESSION_FILE)
    assert info["origin"] == "subagent"
    assert info["parent"] == "session-abc123"
    assert info["title"] is None


def test_scan_splits_main_sub_and_reads_index(tmp_path):
    r = ds.Root(tmp_path)
    make_session(tmp_path, "WS-x", "session-main1", title="M1")
    make_session(tmp_path, "WS-x", "sub-1", title=None, origin="subagent", parent="session-main1")
    make_workspace_json(tmp_path, session_ids=["session-main1"])
    s = ds.scan(r)
    assert len(s["main"]) == 1
    assert len(s["sub"]) == 1
    assert "session-main1" in s["ws_ids"]
    assert s["total"] > 0
    assert s["root"] == str(tmp_path)


def test_delete_then_restore_roundtrip(tmp_path, capsys):
    r = ds.Root(tmp_path)
    d = make_session(tmp_path, "WS-x", "session-rt", title="RT")
    make_workspace_json(tmp_path, session_ids=["session-rt"])

    # 归档
    freed, stamp = ds.op_delete(r, [d], rm=False)
    capsys.readouterr()
    assert freed > 0 and stamp
    s = ds.scan(r)
    assert not s["main"]
    assert len(s["quarantines"]) == 1
    # 索引已移除
    idx = ds.load_index(r)
    assert "session-rt" not in idx["tables"]["workspaces"]["w"]["sessionIds"]
    # manifest 带 BOM、UTF-8（与 DSH 一致）
    manifest = r.quarantine / stamp / "restore-manifest.json"
    raw = manifest.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
    assert entries[0]["sessionId"] == "session-rt"

    # 恢复
    moved, skipped = ds.op_restore(r, stamp)
    assert moved == 1 and skipped == 0
    s2 = ds.scan(r)
    assert len(s2["main"]) == 1
    idx2 = ds.load_index(r)
    assert "session-rt" in idx2["tables"]["workspaces"]["w"]["sessionIds"]


def test_delete_rm_and_purge(tmp_path, capsys):
    r = ds.Root(tmp_path)
    d = make_session(tmp_path, "WS-x", "session-x", title="X")
    make_workspace_json(tmp_path)
    freed, stamp = ds.op_delete(r, [d], rm=True)
    capsys.readouterr()
    assert freed > 0 and stamp is None
    assert not d.exists()

    d2 = make_session(tmp_path, "WS-x", "session-y", title="Y")
    _, stamp2 = ds.op_delete(r, [d2], rm=False)
    freed2, names = ds.op_purge(r, "all")
    assert names == [stamp2] and freed2 > 0
    assert ds.op_purge(r)[1] == []


def test_resolve_ids_prefix_and_subs(tmp_path, capsys):
    r = ds.Root(tmp_path)
    make_session(tmp_path, "WS-x", "session-0497deadbeef", title="父")
    make_session(tmp_path, "WS-x", "sub-0001", title=None, origin="subagent",
                 parent="session-0497deadbeef")
    dirs = ds.resolve_ids(r, ["session-0497"], with_subs=True)
    capsys.readouterr()
    assert {d.name for d in dirs} == {"session-0497deadbeef", "sub-0001"}
    assert ds.resolve_ids(r, ["nope"]) == []


def test_reclaim_orphan_attachments(tmp_path):
    r = ds.Root(tmp_path)
    make_session(tmp_path, "WS-x", "session-a", title=None, attach_refs=[A])
    (r.attach_store / A[:2]).mkdir(parents=True)
    (r.attach_store / A[:2] / A).write_bytes(b"1" * 100)
    (r.attach_store / B[:2]).mkdir(parents=True)
    (r.attach_store / B[:2] / B).write_bytes(b"2" * 200)

    orphans, sz = ds.op_reclaim(r, rm=False)
    assert [f.name for f in orphans] == [B] and sz == 200
    ds.op_reclaim(r, rm=True)
    assert (r.attach_store / B[:2] / B).exists() is False
    assert (r.attach_store / A[:2] / A).exists()


def test_reclaim_counts_quarantined_refs(tmp_path):
    """归档中会话引用的附件不算孤儿。"""
    r = ds.Root(tmp_path)
    d = make_session(tmp_path, "WS-x", "session-q", title=None, attach_refs=[A])
    make_workspace_json(tmp_path)
    ds.op_delete(r, [d], rm=False)
    (r.attach_store / A[:2]).mkdir(parents=True)
    (r.attach_store / A[:2] / A).write_bytes(b"x")
    orphans, _ = ds.op_reclaim(r)
    assert orphans == []


def test_human_and_ftime():
    assert ds.human(1024 * 1.6) == "1.6 KB"
    assert ds.human(5) == "5 B"
    assert ds.ftime(0) == "-"
    assert len(ds.ftime(1_700_000_000_000)) == 11  # MM-DD HH:MM


def test_workspace_json_backup_on_save(tmp_path):
    r = ds.Root(tmp_path)
    make_workspace_json(tmp_path, session_ids=["session-a"])
    ds._remove_from_index(r, {"session-a"})
    assert (r.workspace_json).with_name("workspace.json.bak").exists()
    idx = ds.load_index(r)
    assert idx["tables"]["workspaces"]["w"]["sessionIds"] == []
