# claude-history-session

English | [中文](README.md)

> Close your terminal, reopen it, and bring back — in one sentence — the Claude Code session you were in.

`claude-history-session` is a Claude Code **Skill**: it reads the session transcripts Claude Code writes to disk, lists the most recent session topics in reverse-chronological order, and **resumes the one you pick** — it opens a new terminal window and runs `claude --resume` for you, so there's no copy-pasting.

---

## What problem it solves

Claude Code keeps every session on your local disk, but finding the right one later is awkward:

- After closing the terminal or switching directories, you can't recall what the session was about or what it was called — so `/resume` has nothing to go on;
- The native `/resume` picker only lists sessions for the **current directory**; cross-project ones are invisible;
- Even with a sessionId in hand, you still have to hand-assemble `cd <dir> && claude --resume <id>`.

This skill does all three at once: **list topics → pick one → resume it automatically.**

> The output language is picked automatically from your environment: **Chinese** when the local timezone is UTC+8 or the locale starts with `zh`, **English** otherwise. Force it with `CLAUDE_HISTORY_LANG=zh|en` or `--lang zh|en`.

---

## Preview

Say "what was I working on earlier" inside Claude Code, and it lists your recent sessions:

```
## Recent sessions · All projects · Page 1/7 · 32 total

| #  | Time      | Topic                          | Project               | Session  | Turns |
|----|-----------|--------------------------------|-----------------------|----------|-------|
| 1  | just now  | Fix null pointer in login API  | user-service          | 4caec115 | 42    |
| 2  | 29m ago   | WMS inventory reconciliation   | wms-account-script    | ee0450b8 | 15    |
| 3  | 2h ago    | Python forecast replenish API  | forecast-py           | 249f8d16 | 35    |
| 4  | yesterday | Order state machine design     | order-service         | a28f3897 | 8     |
| 5  | 3d ago    | Debug StarRocks import timeout | data-import           | 3d31cee0 | 27    |

Reply with the **index** to resume a session (a /resume command is shown).
For older sessions, say "next page" or run `--page 2`.
Hidden 15 noise sessions (hello / previous page / next page / untitled). Reply "show all" to list everything.
```

Then you just reply with a number, say `2`:

```
> 2
```

It **opens a new terminal window** already inside that session:

```
Session: WMS inventory reconciliation
Project: /Users/me/interview-prep-java    ID: ee0450b8-...

✅ Opened in a new tmux window
```

---

## Requirements

| Item | Requirement |
|------|-------------|
| Claude Code | Installed and working (CLI required; `claude` must be on your PATH) |
| Python | **3.7+** (the script uses `from __future__ import annotations`; 3.9+ recommended) |
| OS | macOS / Linux / Windows — but **auto-open** differs by platform, see below |

### Cross-platform capability matrix

| Feature | macOS | Windows | Linux / tmux |
|---------|:-----:|:-------:|:------------:|
| List sessions (`list`) | ✅ | ✅ | ✅ |
| Switch within a session (`/resume <id>`) | ✅ | ✅ | ✅ |
| Auto-open a new window (`launch`) | ✅ Terminal / iTerm | ✅ Windows Terminal / cmd | ✅ tmux only |

> When auto-open isn't available, `launch` **degrades gracefully to printing the command** — no error; just paste it into your terminal.

---

## Install

Drop the whole directory into Claude Code's skills folder:

```bash
git clone https://github.com/<your-username>/claude-history-session.git \
  ~/.claude/skills/claude-history-session
```

Windows (PowerShell):

```powershell
git clone https://github.com/<your-username>/claude-history-session.git `
  "$env:USERPROFILE\.claude\skills\claude-history-session"
```

Then restart Claude Code (or start a new session) and the skill is picked up automatically. No other dependencies — the script uses only the Python standard library.

---

## Usage

Two paths: **let Claude drive the skill** (recommended), or **run the script directly**.

### Option 1: natural language inside Claude Code

Once the skill triggers, it shows the list automatically — **you only reply with an index**:

```
You   ▸ what have I been chatting about?

Claude ▸ (lists the 10 most recent session topics automatically, see Preview above)

You   ▸ 2

Claude ▸ (opens a new terminal window, resumes session #2)
```

The trigger phrasing is loose, e.g.:

- "Resume that session where we talked about WMS"
- "Where did we leave off?"
- "Bring back the session where we wrote patches"
- Or type `/claude-history-session` directly

> **Why reply with an index instead of arrow keys?**
> The script runs inside Claude Code, which has no terminal TTY, so it can't pop an interactive menu. Selection is therefore by **replying with an index**. If you really want arrow keys, type `/resume` (no arguments) inside Claude Code to use the native interactive picker.

#### Paging and filtering

When there are many sessions, tell it "next page" or "find ones about deployment". The underlying commands:

```bash
python3 scripts/session_history.py list --page 2      # page 2 (#11-20)
python3 scripts/session_history.py list --page 3 -n 20 # page 3, 20 per page
python3 scripts/session_history.py list --grep deploy  # keep only topics containing "deploy"
python3 scripts/session_history.py list --all         # show all (including hidden noise topics)
```

#### Hiding noise topics

Sessions whose topic is `hello`, `previous page`, `next page`, or `(untitled)` — and their Chinese equivalents `上一页` / `下一页` / `(无标题)` — are **hidden** by default: they tell you nothing about the conversation and aren't worth resuming. Every listing ends with a hint:

```
Hidden 15 noise sessions (hello / previous page / next page / untitled). Reply "show all" to list everything.
```

Say "**show all**" (or add `--all` in the terminal) to include them too.

#### Output language

The script auto-detects the language:

- Timezone is **UTC+8**, or system locale starts with **`zh`** → **Chinese**;
- Otherwise → **English**;
- Override with `CLAUDE_HISTORY_LANG=zh|en` or the `--lang zh|en` flag.

### Option 2: run the script directly

Without going through Claude, run it yourself in a terminal (paths relative to this directory):

```bash
# Default: all projects, latest 20, reverse-chronological
python3 scripts/session_history.py

# Only sessions under the current directory
python3 scripts/session_history.py --current

# Auto-open a new window resuming a session (by sessionId prefix or index)
python3 scripts/session_history.py launch ee0450b8

# Only print the resume command, don't open a window (for manual pasting)
python3 scripts/session_history.py resume ee0450b8
python3 scripts/session_history.py launch ee0450b8 --print
```

#### Subcommands and flags

| Command | Description |
|---------|-------------|
| `list` | List sessions (**default command** — runs when no subcommand is given) |
| `resume <query>` | Resolve the target session and **print only** the resume command |
| `launch <query>` | Resolve the target session, **open a new terminal window** and resume it |

`<query>` accepts three forms: **global index** (e.g. `2`), **sessionId prefix** (e.g. `ee0450b8`), or a **topic keyword** (e.g. `WMS`).

Common `list` flags:

| Flag | Description |
|------|-------------|
| `--current` | Only the current directory's project (default: all projects) |
| `--project <dir>` | Restrict to a specific project directory |
| `-n, --limit <N>` | Rows per page (default 20) |
| `-p, --page <N>` | Page number, starting at 1 |
| `--grep <keyword>` | Filter topics by keyword |
| `--all` | Show everything, without filtering `hello` / `previous page` / `next page` / `(untitled)` noise topics |
| `--lang zh\|en` | Force the output language (overrides timezone/locale detection) |
| `--json` | Emit structured JSON for this page |

> `--all` also applies to `resume` / `launch`: by default they can't resolve hidden sessions; add `--all` to reach them.

---

## How it works

Claude Code writes each session's full transcript to:

```
~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl
```

One JSON object per line. The script reads key records to distill a "topic":

- **`ai-title`** — the short title Claude generates for the session, **the preferred topic source**;
- **`last-prompt`** — the session's most recent prompt, the fallback;
- If neither exists, it falls back to the **first real user message** (skipping local commands like `/clear` and `/resume`, and sub-agent conversations).

Other handling:

- If a session changed working directories mid-flight, it appears under two project directories — deduplicated by `sessionId`, keeping the newest copy;
- Sorted by **most recent activity**, rendered as `just now / Nm ago / Nh ago / Nd ago / absolute time`;
- The session directory can be overridden with the `CLAUDE_CONFIG_DIR` env var (defaults to `~/.claude`).

---

## FAQ

**Q: `launch` says "auto-open is not supported in this environment"?**
You're on non-macOS and not inside tmux (Windows is supported). The command is printed for you to paste and run.

**Q: macOS auto-open throws a permission error the first time?**
That's the system "Automation" permission not granted: **System Settings → Privacy & Security → Automation**, allow Terminal to control Terminal.

**Q: Why can't I select with arrow keys?**
See "Why reply with an index" above. The script runs without a TTY and can't reach `/dev/tty`.

**Q: I don't see some sessions in the list, e.g. ones titled `hello` / `next page` / `(untitled)`?**
Those topics (`hello`, `previous page`, `next page`, `(untitled)` and their Chinese forms) are **hidden** by default because they tell you nothing. Say "show all", or append `--all` to the command, to see everything.

**Q: A session belongs to another project directory and `/resume` can't find it?**
`/resume <id>` is filtered by the current directory in some versions. For cross-project sessions, `cd <that-directory>` first, or use `launch` (which carries the right directory for you).

---

## Directory layout

```
claude-history-session/
├── SKILL.md               # Skill definition (instructions for Claude)
├── README.md              # README (Chinese)
├── README.en.md           # This file (English)
└── scripts/
    └── session_history.py # Core script: parse sessions, list topics, generate/run resume commands
```

---

## License

MIT
