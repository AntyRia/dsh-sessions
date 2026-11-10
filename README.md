# dsh-sessions

<p align="center">
  <a href="README.zh.md"><b>简体中文</b></a> | English
</p>

A session manager and disk reclaimer for **DeepSeek Harness (DSH)**.
It reads and writes DSH's local storage directly, so the session list is
**always in sync with DSH itself** — and where DSH's UI can only archive,
this tool can really delete.

- **List** every session (main + hidden subagent sessions) with size,
  created/last-activity time and index state — live, no DSH restart needed.
- **Archive** sessions to a quarantine area (compatible with DSH's own
  `restore-manifest.json` format) or **delete them for good**.
- **Restore / clear** quarantine entries, **reclaim orphaned attachments**
  (sha256 content-addressed blobs no longer referenced by any session).
- **Auto-detect the DSH storage root** (`DSH_HOME` env → last used →
  `~/.dsh` → other user profiles) or **pick one manually**.
- **CLI + tkinter GUI** (light theme), sharing the same storage engine.

## Features

- **Live sync** — every operation reads DSH's real on-disk state
  (`sessions/`, `storages/workspace.json`, `deleted-sessions/`,
  `attachments/`); nothing is cached.
- **Safe by default** — deleting archives into a quarantine first;
  restore it anytime. The quarantine format matches DSH's, so DSH and this
  tool can restore each other's sessions. `workspace.json` is backed up to
  `.bak` before every index edit.
- **Path detection** — the DSH storage root is detected automatically
  (env var → remembered choice → `~/.dsh` → other local user profiles on
  Windows), can be picked by hand in the GUI (`选择路径…`) or passed via
  `--root` / `DSH_HOME`. `dsh-sessions doctor` shows every candidate and
  why it was/wasn't accepted.
- **Disk reports** — per-directory usage of the DSH root plus free space of
  the disk it lives on (Windows uses the same API Explorer uses).
- **Subagent awareness** — hidden `origin=subagent` sessions (invisible in
  DSH's sidebar) are listed separately and can be included in deletes.
- **DSH running guard** — the desktop app is detected via its lockfile /
  process name; the GUI asks before mutating while it runs.

## Requirements

| Piece | Need |
| --- | --- |
| Python | 3.9+ (standard library `tkinter` for the GUI) |
| `zstandard` | ≥ 0.4 (`pip install zstandard`) |

DSH itself is *not* bundled — this tool works on its storage directory,
which is created by DSH (default `~/.dsh`).

## Quick start

**1. Install** (pick one):

- Clone and run from source (no install needed):

  ```bash
  git clone https://github.com/AntyRia/dsh-sessions.git && cd dsh-sessions
  python -m dsh_sessions.cli          # CLI
  python -m dsh_sessions.gui          # GUI
  ```

- Install as a package (creates `dsh-sessions` / `dsh-sessions-gui` commands):

  ```bash
  pip install .
  dsh-sessions list
  dsh-sessions-gui
  ```

  On Windows, `scripts/dsh-sessions.bat` / `scripts/dsh-sessions-gui.bat`
  also work straight from a checkout.

**2. Check the environment**:

```bash
dsh-sessions doctor     # storage-root detection, DSH running state, disk
```

**3. Use it**:

```bash
dsh-sessions                       # = list (live sync)
dsh-sessions delete <id-prefix>    # archive to quarantine (reversible)
dsh-sessions delete --rm <id>      # delete for good
dsh-sessions restore <stamp>       # restore from quarantine
dsh-sessions purge all             # clear the quarantine permanently
dsh-sessions reclaim --rm          # delete orphaned attachments
dsh-sessions space                 # disk usage report
```

> IDs accept prefixes, e.g. `dsh-sessions delete session-0497`.

## Storage root detection

The tool must know where DSH stores its data. Candidates are tried in
order; the first directory that contains `sessions/` **or**
`storages/workspace.json` wins:

1. `DSH_HOME` environment variable (explicit override)
2. The path you last used (remembered in the config dir)
3. `~/.dsh` (the default)
4. Other local user profiles' `.dsh` (Windows only, `C:\Users\<user>\.dsh`)

In the GUI the current root is shown at the top of the window:

- **自动检测** re-runs detection and switches to the first valid candidate;
- **选择路径…** opens a folder dialog for any directory (including another
  profile's or a synced folder); the choice is remembered.

The config lives in `%APPDATA%/dsh-sessions/config.json` (Windows) or
`$XDG_CONFIG_HOME/dsh-sessions/config.json` (elsewhere). Deleting the
folder removes the remembered root / auto-refresh preference — session
data itself is never stored there.

## Usage

### CLI commands

| Command | Description |
| --- | --- |
| `dsh-sessions` (no args) | Same as `list`. |
| `dsh-sessions list` | Live-sync list of all sessions (main, subagent, quarantine). |
| `dsh-sessions space` | Disk usage report for the DSH root + free space of its disk. |
| `dsh-sessions delete <id…> [--rm] [--subs]` | Archive (default) or permanently delete sessions. `--subs` includes subagent children. |
| `dsh-sessions restore <stamp>` | Restore a quarantine entry (prints the list when omitted). |
| `dsh-sessions purge [stamp\|all]` | Permanently delete quarantine entries (default: the newest). |
| `dsh-sessions reclaim [--rm]` | List (or with `--rm`, delete) attachments no session references. |
| `dsh-sessions doctor` | Environment check: detection candidates, DSH state, disk. |

Global option: `--root PATH` — use a specific storage root for this run.

### GUI

Light-themed tkinter window (the same engine, a 5 s auto-refresh that only
rebuilds the tables when data actually changed):

- **Left** — sessions grouped into *main* and *hidden subagent*; archive /
  delete / copy ID; double-click for details (parent, message count, path).
- **Right** — quarantine entries; restore / clear; double-click for the
  manifest.
- **Top** — storage root + **auto-detect / pick path**; filter box
  (`Ctrl+F`); refresh (F5).
- **Bottom status bar** — DSH running state (dot + label), session /
  quarantine counts, total size, a disk-usage meter on the root's drive,
  full session ID on hover, and the last operation's receipt.
- `Ctrl` for multi-select; clicking a group header selects the whole group;
  `Del` deletes the selection.

## DSH storage format (brief)

```
<root>/                                   # default ~/.dsh
  sessions/<workspace>/<session-id>/
      session.v4.jsonl.zstd               # zstd-compressed JSONL
  storages/workspace.json                 # index (sessionIds/archived/pinned)
  storages/session_projcache/sessions/<id>.json
  deleted-sessions/<YYYYmmdd-HHMMSS>/     # quarantine
      restore-manifest.json               # BOM + UTF-8, 4-space indent
  attachments/v1/objects/<2hex>/<sha256>  # read-only content-addressed blobs
```

Session files are *multi-frame* zstd streams of JSONL records
(`session`, `session/title`, `user/message`, … with millisecond `time`).
Attachments are referenced inside sessions as `sha256:<hash>` and carry
the OS read-only attribute — both quirks are handled.
See [docs/storage-format.md](docs/storage-format.md).

## FAQ

- **"建议先退出 DSH 再操作" (quit DSH first)?** — DSH keeps file locks and
  an in-memory index while running. Read-only operations (list/space) are
  always safe; mutations work while DSH runs but the app will re-read the
  disk on next refresh. For restores, quit and restart DSH to see the
  sessions.
- **Why does C: show a different free space than Explorer?** — the tool uses
  `GetDiskFreeSpaceExW`'s *available* value, the same one Explorer shows.
- **A session shows 状态=索引外 (out of index)?** — its files exist but
  `workspace.json` no longer lists it (e.g. created by another DSH profile
  or after a partial delete). It still counts for size and can be deleted.
- **Can DSH restore an entry this tool archived?** — Yes: the quarantine
  manifest format is byte-compatible (BOM, UTF-8, 4-space indent).

## Development

```bash
git clone https://github.com/AntyRia/dsh-sessions.git && cd dsh-sessions
pip install -e ".[dev]"
pytest -q
```

Project layout:

```
src/dsh_sessions/
  store.py    # storage engine (parse / scan / ops) — no global state
  detect.py   # storage-root detection + config persistence
  cli.py      # argparse CLI
  gui.py      # tkinter GUI (light theme)
tests/        # unit tests with synthetic .dsh fixtures
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the invariants that must hold.

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Acknowledgments

- **HyperRoute · 超路由** — [hyperroute.cc](https://hyperroute.cc) — model
  relay access (GPT / Claude) that works out of the box; thank you for the
  support.
- **linux.do** — [linux.do](https://linux.do/) — the open technical
  community where much of this project's discussion and feedback happens;
  thank you.

## License

[MIT](LICENSE). The software is provided "as is", without warranty of any
kind. You are responsible for the sessions you delete.
