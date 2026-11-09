# DSH 本地存储格式（观察记录）

本文档整理自 DeepSeek Harness（DSH）实际产生的本地文件，供理解
dsh-sessions 的读写行为；DSH 官方目前未提供存储格式说明。

## 目录布局

默认根目录 `~/.dsh`（可被 `DSH_HOME` 覆盖）：

```
.dsh/
  sessions/                            # 全部会话，按 workspace 分子目录
    <mangled-ws-path>/                 # workspace 路径转义的目录名
      <session-id>/
        session.v4.jsonl.zstd          # 会话本体（多帧 zstd 的 JSONL）
  storages/
    workspace.json                     # 会话索引
    session_projcache/sessions/<id>.json  # 会话投影缓存
  deleted-sessions/                    # 隔离区（DSH 的"归档"）
    <YYYYmmdd-HHMMSS>/
      restore-manifest.json            # 恢复清单（BOM + UTF-8）
      sessions/<session-id>/...        # 被移出的会话目录
      projcache/<session-id>.json      # 被移出的投影缓存（若有）
      README.txt
  attachments/
    v1/objects/<2hex>/<64hex>          # 附件对象：sha256 内容寻址，只读
  dsh-runtimes/                        # 运行时临时目录
  cache/                               # 其他缓存
  llm-deepseek/ profiles/              # 模型 / 配置
```

桌面端（Electron）数据另在 `%APPDATA%\@deepseek-ai\dsh-desktop`
（缓存、lockfile 等），与会话存储相互独立。

## 会话文件 `session.v4.jsonl.zstd`

- **多帧 zstd** 流，内部为 JSONL（每行一个 JSON 对象）。解压必须整体
  流式读取：

  ```python
  zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
  ```

  `decompressobj` 只解第一帧，会丢后面的记录。
- 记录类型（观察到的）：`session`（id / `createdAt` / `origin` /
  `parentSession`）、`session/title`（`data.title`，可多次更新，取最后
  一次）、`user/message`、`message` 等；时间字段 `time` 为**毫秒**。
- `origin == "subagent"` 且 `parentSession` 指向主会话 → 隐藏子会话，
  DSH 侧栏不显示；主会话 id 以 `session-` 开头，子会话为纯 UUID。

## 索引 `storages/workspace.json`

- 顶层 `global` 与 `tables.workspaces.<wid>` 两层，均含
  `sessionIds` / `archivedSessionIds` / `pinnedSessionIds` 数组。
- dsh-sessions 写索引前备份 `workspace.json.bak`；归档 / 删除从两处
  数组中移除 id，恢复时写回。

## 隔离区 `deleted-sessions/<stamp>/`

- `restore-manifest.json`：**UTF-8 BOM 开头**、`ensure_ascii=False`、
  4 空格缩进；条目字段：
  - `sessionId` —— 会话 id
  - `original` —— 原会话目录绝对路径
  - `quarantined` —— 隔离区内会话目录绝对路径
  - `cacheOriginal` / `cacheQuarantined` —— 仅当存在投影缓存时写入
- DSH 归档时写同一格式的清单；dsh-sessions 归档时同样写该格式，
  因此两边互认、互相可恢复。

## 附件 `attachments/v1/objects/`

- 文件名即内容 sha256：`objects/<前 2 位 hex>/<64 位 hex>`。
- 会话内以 `sha256:<hash>` 字符串引用。
- 文件带 **OS 只读属性**——删除前需先 `chmod +w`（父目录清空时同理）。
- 「孤儿」= 对象文件存在，但 `sessions/` 与 `deleted-sessions/` 下所有
  会话文件都不再引用其 hash。注意归档中的会话仍算引用方。

## 已知坑

| 坑 | 现象 | 处理 |
| --- | --- | --- |
| 多帧 zstd | `decompressobj` 只读第一帧，解析出半份会话 | `stream_reader` 整体读 |
| manifest BOM | `json.loads(text)` 抛 `Extra data` | `encoding="utf-8-sig"` |
| 只读附件 | `PermissionError (WinError 5)` | 删除前 `chmod +w` |
| Windows 盘口径 | `shutil.disk_usage.free` 与资源管理器不符 | `GetDiskFreeSpaceExW` 的 available |
| lockfile mtime | 只在 DSH 启动时写一次，运行中不更新 | 进程名（含 "deepseek"）兜底检测 |
| 子会话不在侧栏 | 用户以为会话"凭空消失" | 单独分组列出 |
