"""dsh-sessions — DeepSeek Harness (DSH) 会话管理（CLI + tkinter GUI）。

直接读写 DSH 的本地存储（默认 ~/.dsh），列表永远与 DSH 实时同步：
归档、永久删除、隔离区恢复/清除、孤儿附件回收，以及磁盘占用报告。

库用法::

    from dsh_sessions import Root, scan, op_delete, op_restore

    s = scan(Root("~/.dsh"))
"""
from .store import (
    SESSION_FILE,
    Root,
    dsh_running,
    desktop_data,
    disk_info,
    ftime,
    human,
    op_delete,
    op_purge,
    op_reclaim,
    op_restore,
    parse_session,
    scan,
)
from . import detect  # 模块（勿在此 re-export 同名函数，会遮蔽子模块属性）
from .detect import Candidate, resolve

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SESSION_FILE",
    "Root",
    "Candidate",
    "detect",
    "resolve",
    "scan",
    "parse_session",
    "op_delete",
    "op_restore",
    "op_purge",
    "op_reclaim",
    "dsh_running",
    "desktop_data",
    "disk_info",
    "human",
    "ftime",
]
