# 贡献指南

感谢关注 dsh-sessions！

## 项目结构

```
src/dsh_sessions/
  store.py    # 存储引擎：会话解析、扫描、归档/恢复/清除、孤儿附件、磁盘
  detect.py   # 存储根自动检测 + 配置持久化
  cli.py      # argparse CLI
  gui.py      # tkinter GUI（浅色主题）
tests/        # pytest 单测（合成 .dsh fixture，不依赖真实存储）
scripts/      # Windows 启动 .bat
docs/         # 存储格式等长文
```

## 开发与测试

```bash
pip install -e ".[dev]"
pytest -q
```

新增行为必须补对应单测：`store` 用 `tests/helpers.py` 的
`make_session` / `make_workspace_json` 构造合成根目录，`detect` 用
monkeypatch 控制 `DSH_HOME` / `APPDATA` / `Path.home`。

## 必须保持的安全不变量

这些是工具与 DSH 互通 / 数据不丢的底线，改动前先在这里登记并补测试：

1. **manifest 格式** —— `restore-manifest.json` 必须以 UTF-8 BOM 开头、
   4 空格缩进、`ensure_ascii=False`；字段 `sessionId` / `original` /
   `quarantined` 必有，`cacheOriginal` / `cacheQuarantined` 仅在存在投影
   缓存时写入。这是 DSH 能恢复本工具隔离区的前提。
2. **索引备份** —— 每次写 `workspace.json` 前先复制 `workspace.json.bak`
   （`save_index`）。
3. **zstd 多帧** —— 会话文件必须用 `ZstdDecompressor().stream_reader()`
   整体解压（`decompressobj` 只读第一帧，会丢数据）。
4. **只读附件** —— `attachments/` 对象带 OS 只读属性；删除前必须
   `chmod +w`（`op_reclaim` / `op_delete --rm`），父目录清空时同样处理。
5. **孤儿判定** —— 附件引用集合必须同时覆盖 `sessions/` 与
   `deleted-sessions/`（归档中的会话仍持有引用）。
6. **时间戳** —— 会话记录 `time` / `createdAt` 是**毫秒**；隔离区目录名
   `YYYYmmdd-HHMMSS` 同时是排序键，勿改格式。
7. **检测优先级** —— `DSH_HOME` > 上次选择 > `~/.dsh` > 其他用户目录
   （见 `detect.candidates()`）；有效性判定固定为「含 `sessions/` 或
   `storages/workspace.json`」。
8. **Windows 磁盘口径** —— `disk_info` 在 Windows 上必须用
   `GetDiskFreeSpaceExW` 的 available 值（资源管理器口径）；
   `shutil.disk_usage` 仅作为非 Windows 回退。

## 提交约定

- 小步提交，一条 commit 一件事；消息用中文或英文均可，动词开头。
- GUI 改动请附截图；涉及布局 / 配色的改动说明主题（当前为 Catppuccin
  Latte 浅色，深色值保留在 `gui.py` 顶部注释）。
- 版本号在 `pyproject.toml` 与 `src/dsh_sessions/__init__.py` 两处同步
  更新，并在 `CHANGELOG.md` 增加条目。

## 界面规范（GUI）

遵循「数据可视化」习惯：状态色只配合图标 / 文字使用（绿 / 橙 / 红 =
正常 / 警告 / 危险，不单独承载含义）；表格用细线与弱色分隔，选中行用
低饱和蓝；磁盘用量条阈值 <70% 绿、<90% 橙、≥90% 红并直接标注数值。
修改色板时保持文字对比度可读（主文本 ≥ 4.5:1）。
