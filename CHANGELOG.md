# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] - 2026-11-09

首个开源版本。

### 新增

- **CLI**：`list`（默认，实时同步全部会话）、`space`（磁盘占用报告）、
  `delete`（归档 / `--rm` 永久删除 / `--subs` 连带子会话）、`restore`、
  `purge`、`reclaim`（孤儿附件回收）、`doctor`（环境体检）。
- **存储根自动检测**：`DSH_HOME` 环境变量 → 上次选择 → `~/.dsh` →
  其他本地用户目录（Windows）；CLI 支持 `--root PATH` 手动指定。
- **GUI**（tkinter 浅色主题）：会话表（主会话 / 隐藏子会话分组、隔行色、
  悬停完整 ID、过滤占位符、智能刷新——数据不变不重建表格）、隔离区
  （恢复 / 清除 / manifest 详情）、顶部存储根路径 + 自动检测 / 手动选择
  路径（选择持久化到配置目录）、底部状态栏指标行（DSH 运行状态点、
  会话 / 隔离区计数、会话总量、磁盘用量条、操作回执）。
- **库**：`store.Root` / `scan()` / `op_delete()` / `op_restore()` /
  `op_purge()` / `op_reclaim()` / `parse_session()` / `disk_info()` 等，
  无全局状态，可 import 使用。
- **可移植性**：会话解析 / 扫描 / 全部操作函数以 `Root` 为参；
  `zstandard` 缺失时退化为只读目录模式；非 Windows 平台磁盘 / 运行状态
  检测有回退。
- **测试**：基于合成 `.dsh` fixture 的单测（解析、扫描、归档/恢复往返、
  清除、孤儿附件、索引备份、检测优先级）。

### 兼容性说明

- 隔离区 `restore-manifest.json` 与 DSH 自带格式逐字节兼容
  （BOM + UTF-8 + 4 空格缩进），双向可恢复。
- 修改 `workspace.json` 前自动备份 `workspace.json.bak`。
