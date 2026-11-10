# dsh-sessions

<p align="center">
  <b>简体中文</b> | <a href="README.md">English</a>
</p>

面向 **DeepSeek Harness（DSH）** 的会话管理与磁盘回收工具。
直接读写 DSH 的本地存储，会话列表**永远与 DSH 实时同步**——DSH 界面
目前只能归档，这里可以真正删除。

- **列出**全部会话（主会话 + 隐藏的 subagent 子会话）：大小、创建 /
  最近活动时间、索引状态，实时读取，无需重启 DSH。
- **归档**会话到隔离区（与 DSH 自带 `restore-manifest.json` 格式互通），
  或**永久删除**。
- **恢复 / 清除**隔离区，**回收孤儿附件**（不再被任何会话引用的
  sha256 内容寻址对象）。
- **自动检测 DSH 存储路径**（`DSH_HOME` 环境变量 → 上次选择 → `~/.dsh`
  → 其他用户目录），也可**手动选择**任意路径。
- **CLI + tkinter GUI**（浅色主题），共用同一套存储引擎。

- [简介](#简介)
- [功能特性](#功能特性)
- [运行前提](#运行前提)
- [快速上手](#快速上手)
- [存储路径检测](#存储路径检测)
- [使用](#使用)
- [界面导览](#界面导览)
- [DSH 存储格式](#dsh-存储格式)
- [常见问题](#常见问题)
- [开发](#开发)
- [参与贡献](#参与贡献)
- [致谢](#致谢)
- [开源协议](#开源协议)

## 简介

### 要解决的问题

DSH 的会话、附件都落在本地 `~/.dsh` 里，会越攒越大，而 DSH 桌面端目前
只提供了「归档」，没有真正的删除与空间统计：

- **归档 ≠ 腾空间。** 会话进了 `deleted-sessions/` 隔离区，磁盘占用一分
  没少。
- **隐藏占用看不见。** subagent 子会话不在侧栏显示，附件对象
  （`attachments/`）随会话删除后可能残留成孤儿。
- **没有工具口径的空间报告。** 想知道 `.dsh` 到底占了多少、盘里还剩
  多少，只能靠翻文件夹。

### 解决思路

dsh-sessions 直接读写 DSH 的本地存储，把「同步、删除、回收」做成一步
操作，全程与 DSH 文件格式兼容：

```text
DSH 本地存储 (~/.dsh)
        |
        v
实时扫描 (sessions/ + workspace.json 索引)
        |
        v
归档 (deleted-sessions/ 隔离区, manifest 与 DSH 互通)
  / 恢复 / 清除
        |
        v
永久删除 + 孤儿附件回收 → 真正腾出磁盘空间
```

## 功能特性

- **实时同步** —— 每次操作都读 DSH 的真实磁盘状态（`sessions/`、
  `storages/workspace.json`、`deleted-sessions/`、`attachments/`），
  不缓存、不经过 DSH 界面。
- **默认安全** —— 删除先进隔离区，可随时 `restore` 找回；隔离区格式与
  DSH 自带格式一致（BOM + UTF-8 + 4 空格缩进），两边可互相恢复；
  修改索引前自动备份 `workspace.json.bak`。
- **路径检测** —— DSH 存储根目录自动检测（环境变量 → 上次选择 →
  `~/.dsh` → 其他本地用户目录），GUI 顶部可**手动选择**任意目录并记住，
  CLI 支持 `--root`；`dsh-sessions doctor` 展示每个候选的判定结果。
- **磁盘报告** —— DSH 根目录逐目录占用 + 所在磁盘剩余空间
  （Windows 用与资源管理器相同的 WinAPI 口径）。
- **子会话感知** —— `origin=subagent` 的隐藏会话单独分组列出，删除时
  可选 `--subs` 一并处理。
- **运行中保护** —— 通过 lockfile / 进程名检测 DSH 桌面端是否运行；
  GUI 在运行中做写操作前会弹确认。

## 运行前提

| 依赖 | 说明 |
| --- | --- |
| Python | 3.9+（GUI 需要标准库 `tkinter`） |
| `zstandard` | ≥ 0.4，`pip install zstandard` |

DSH 本体不随本工具分发——本工具操作的是 DSH 创建的存储目录
（默认 `~/.dsh`），先安装并至少启动过一次 DSH 才有内容可管理。

## 快速上手

**第 1 步——获取**（任选其一）：

- 源码直接运行（无需安装）：

  ```bash
  git clone https://github.com/AntyRia/dsh-sessions.git && cd dsh-sessions
  python -m dsh_sessions.cli      # CLI
  python -m dsh_sessions.gui      # GUI
  ```

  Windows 下也可以直接双击 `scripts/dsh-sessions.bat` /
  `scripts/dsh-sessions-gui.bat`。

- 安装为命令：

  ```bash
  pip install .
  dsh-sessions list        # CLI
  dsh-sessions-gui         # GUI
  ```

**第 2 步——检查环境**：

```bash
dsh-sessions doctor      # 存储根检测 / DSH 运行状态 / 磁盘空间
```

**第 3 步——使用**：

```bash
dsh-sessions                       # 实时同步列出全部会话（默认命令）
dsh-sessions delete <id前缀>       # 归档到隔离区（可恢复）
dsh-sessions delete --rm <id>      # 永久删除
dsh-sessions restore <时间戳>      # 从隔离区恢复
dsh-sessions purge all             # 永久清除全部隔离区
dsh-sessions reclaim --rm          # 回收孤儿附件
dsh-sessions space                 # 磁盘占用报告
```

> id 支持前缀匹配，例如 `dsh-sessions delete session-0497`。

## 存储路径检测

工具需要先定位 DSH 的存储目录。候选按优先级依次尝试，**第一个包含
`sessions/` 或 `storages/workspace.json` 的目录胜出**：

1. `DSH_HOME` 环境变量（显式覆盖，最高优先级）
2. 上次使用的路径（记录在配置目录，GUI 里手动选择或检测后写入）
3. `~/.dsh`（默认）
4. 其他本地用户目录的 `.dsh`（仅 Windows，`C:\Users\<用户>\.dsh`）

GUI 窗口顶部始终显示当前使用的存储根及其来源：

- **自动检测** —— 重新执行检测，切换到第一个有效候选；
- **选择路径…** —— 打开目录选择框，可指向任意位置（其他用户目录、
  同步盘等），选择会被记住；目录不满足条件时会先征求确认。

配置文件位于 `%APPDATA%/dsh-sessions/config.json`（Windows）或
`$XDG_CONFIG_HOME/dsh-sessions/config.json`（其他平台），只存
「上次选择的路径 + 自动刷新开关」；会话数据本身从不写入该目录。

## 使用

### 命令一览

| 命令 | 说明 |
| --- | --- |
| `dsh-sessions`（不带参数） | 等同于 `list`。 |
| `dsh-sessions list` | 实时同步列出全部会话（主会话 / 子会话 / 隔离区）。 |
| `dsh-sessions space` | DSH 根目录逐目录占用 + 所在磁盘剩余空间。 |
| `dsh-sessions delete <id…> [--rm] [--subs]` | 归档（默认）或永久删除会话；`--subs` 连带子会话。 |
| `dsh-sessions restore <时间戳>` | 从隔离区恢复（不带参数时列出可用项）。 |
| `dsh-sessions purge [时间戳\|all]` | 永久删除隔离区（默认最近一个）。 |
| `dsh-sessions reclaim [--rm]` | 列出孤儿附件（`--rm` 时真正删除）。 |
| `dsh-sessions doctor` | 环境体检：检测候选、DSH 运行状态、磁盘。 |

全局选项：`--root PATH` —— 本次运行指定存储根（覆盖自动检测）。

### 示例

```bash
# 体检 + 查看
dsh-sessions doctor
dsh-sessions space

# 归档两个会话（id 前缀），之后随时可恢复
dsh-sessions delete session-0497 session-187a

# 永久删除（不可恢复）
dsh-sessions delete --rm session-0497

# 恢复最近一个隔离区；或清空全部
dsh-sessions restore 20261109-163000
dsh-sessions purge all

# 回收不再被引用的附件（先列出，确认后再删）
dsh-sessions reclaim
dsh-sessions reclaim --rm
```

## 界面导览

tkinter 浅色主题窗口，与 CLI 共用存储引擎；5 秒自动刷新，且**数据没有
变化时不重建表格**（保留选中与滚动位置）：

- **顶部** —— 标题 + 版本号；存储根路径及其来源（默认 / DSH_HOME /
  上次选择 / 手动指定）；**自动检测** 与 **选择路径…** 按钮；
  过滤框（`Ctrl+F` 聚焦，`Esc` 清空）；**自动刷新** 开关；**刷新**
  （F5）。
- **左侧：会话** —— 分「主会话」与「隐藏子会话 (subagent)」两组，
  列：ID（缩写）、标题、创建、最近活动、大小、状态（已固定 / 已归档 /
  索引内 / 索引外）；操作：归档（蓝色）、永久删除（红色 / Del 键）、
  复制 ID；双击查看会话详情（父会话、消息数、路径等）。
- **右侧：隔离区** —— deleted-sessions 下的各时间戳目录；
  恢复（绿色）、清除（橙色）；双击查看 manifest 内容。
- **底部状态栏** —— DSH 运行状态（状态点 + 文字，颜色不单独承载含义）、
  会话数、隔离区数、会话总量、存储根所在磁盘的用量条（<70% 绿 /
  <90% 橙 / ≥90% 红 + 直接标注）、悬停行的完整会话 ID、最近一次操作回执。
- 选择：`Ctrl` 多选；点分组标题 = 选整组；`Del` 删除所选。

## DSH 存储格式

```
<root>/                                   # 默认 ~/.dsh
  sessions/<workspace>/<session-id>/
      session.v4.jsonl.zstd               # zstd 压缩的 JSONL（多帧）
  storages/workspace.json                 # 索引（sessionIds/archived/pinned）
  storages/session_projcache/sessions/<id>.json   # 投影缓存
  deleted-sessions/<YYYYmmdd-HHMMSS>/     # 隔离区
      restore-manifest.json               # BOM + UTF-8 + 4 空格缩进
      README.txt
  attachments/v1/objects/<2hex>/<sha256>  # 只读、内容寻址附件
```

会话文件是**多帧 zstd** 流的 JSONL 记录（`session`、`session/title`、
`user/message` 等，`time` 为毫秒时间戳）；附件在会话内以
`sha256:<hash>` 引用，且被 DSH 设为只读——两个坑本工具都已处理。
完整说明见 [docs/storage-format.md](docs/storage-format.md)。

## 常见问题

- **为什么要先退出 DSH 再操作？** —— DSH 运行时持有文件锁与内存索引。
  只读操作（list / space / 查看）随时安全；写操作（删除 / 恢复）运行时
  也能做，但 DSH 下次刷新才会反映磁盘变化。恢复后请重启 DSH 查看。
- **C 盘剩余空间和资源管理器对不上？** —— 工具使用
  `GetDiskFreeSpaceExW` 的 *available* 值，即资源管理器显示的口径
  （`shutil.disk_usage` 在 Windows 上是另一个口径）。
- **状态=「索引外」是什么意思？** —— 会话文件存在，但
  `workspace.json` 已不列出它（例如别的 DSH profile 建的、或索引被
  外部改动过）。它照常计入体积，也照常可以删除。
- **DSH 能恢复本工具归档的隔离区吗？** —— 能。manifest 逐字节兼容
  （BOM、UTF-8、4 空格缩进）。
- **换机器 / 其他用户目录的 `.dsh` 能用吗？** —— 能：GUI「选择路径…」
  或 CLI `--root` 指向该目录即可，检测器在 Windows 上也会把其他用户
  目录的 `.dsh` 作为兜底候选。

## 开发

```bash
git clone https://github.com/AntyRia/dsh-sessions.git && cd dsh-sessions
pip install -e ".[dev]"
pytest -q
```

项目结构：

```
src/dsh_sessions/
  store.py    # 存储引擎（解析 / 扫描 / 操作），无全局状态，全部以 Root 为参
  detect.py   # 存储根自动检测 + 配置持久化
  cli.py      # argparse CLI
  gui.py      # tkinter GUI（浅色主题）
tests/        # 基于合成 .dsh fixture 的单测
```

必须保持的安全不变量（manifest 格式、索引备份、只读附件处理等）见
[CONTRIBUTING.md](CONTRIBUTING.md)。

## 参与贡献

欢迎 PR 与 issue——约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 致谢

- **HyperRoute · 超路由** —— [hyperroute.cc](https://hyperroute.cc) ——
  开箱即用的模型中转接入（GPT / Claude），感谢支持。
- **linux.do** —— [linux.do](https://linux.do/) —— 开放的技术社区，本
  项目的许多讨论与反馈都发生在这里，谢谢大家。

## 开源协议

[MIT](LICENSE) —— 完整文本见 [LICENSE](LICENSE) 文件。

本软件按「现状」提供，不提供任何形式的担保。你需对通过本工具删除的
会话与附件自行负责。
