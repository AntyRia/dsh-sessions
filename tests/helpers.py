# -*- coding: utf-8 -*-
"""共享 helper：构造一个合成的 DSH 存储根目录（供单测使用）。"""
import json
from pathlib import Path

import zstandard

from dsh_sessions import store as ds


def make_session(root: Path, ws: str, sid: str, title="测试会话", origin=None,
                 parent=None, created=1_700_000_000_000, user_msgs=1,
                 attach_refs=()) -> Path:
    """在 root/sessions/<ws>/<sid>/ 下写一个 zstd JSONL 会话文件。"""
    d = root / "sessions" / ws / sid
    d.mkdir(parents=True, exist_ok=True)
    recs = [{"type": "session", "id": sid, "createdAt": created,
             "origin": origin, "parentSession": parent}]
    if title:
        recs.append({"type": "session/title", "data": {"title": title},
                     "time": created + 1000})
    for _ in range(user_msgs):
        recs.append({"type": "user/message", "text": "hi", "time": created + 2000})
    for h in attach_refs:
        recs.append({"type": "message", "text": f"file sha256:{h}", "time": created + 3000})
    blob = b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in recs)
    (d / ds.SESSION_FILE).write_bytes(zstandard.ZstdCompressor().compress(blob))
    return d


def make_workspace_json(root: Path, session_ids=(), archived=(), pinned=()):
    (root / "storages").mkdir(parents=True, exist_ok=True)
    (root / "storages" / "workspace.json").write_text(
        json.dumps({"global": {"archivedSessionIds": list(archived),
                               "pinnedSessionIds": list(pinned)},
                    "tables": {"workspaces": {"w": {
                        "sessionIds": list(session_ids),
                        "archivedSessionIds": list(archived),
                        "pinnedSessionIds": list(pinned)}}}},
                   ensure_ascii=False), encoding="utf-8")
