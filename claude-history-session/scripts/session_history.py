#!/usr/bin/env python3
"""List Claude Code sessions with their topics, and build resume commands.

Sessions live in ~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl. Each line
is a JSON record; the interesting ones are:
  user / assistant   conversation turns (isSidechain=true means a subagent)
  ai-title           an AI-generated short title for the session (the "topic")
  last-prompt        the most recent user prompt

The goal is narrow: help a user who reopened their terminal figure out which
conversation to jump back into, and hand them the exact command to do it.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
PROJECTS_DIR = CLAUDE_DIR / "projects"

COMMAND_TAG_RE = re.compile(r"<command-(?:name|message)>.*?</command-(?:name|message)>", re.S)
COMMAND_ARGS_TAG_RE = re.compile(r"</?command-args>")
LOCAL_CMD_RE = re.compile(r"<local-command[^>]*>.*?</local-command[^>]*>", re.S)
ANY_TAG_RE = re.compile(r"<[^>]+>")
COMMAND_NAME_RE = re.compile(r"<command-name>\s*(/[A-Za-z][\w-]*)")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

# ---------------------------------------------------------------------------
# i18n. The script speaks Chinese on a UTC+8 / Chinese-locale machine and
# English everywhere else. Override with CLAUDE_HISTORY_LANG=zh|en or --lang.
# ---------------------------------------------------------------------------


def _locale_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val:
            return val
    try:
        import locale
        return locale.getlocale(locale.LC_MESSAGES)[0] or ""
    except Exception:
        return ""


def detect_lang() -> str:
    override = os.environ.get("CLAUDE_HISTORY_LANG", "").strip().lower()
    if override.startswith("zh"):
        return "zh"
    if override.startswith("en"):
        return "en"
    if _locale_lang().lower().startswith("zh"):
        return "zh"
    if datetime.now().astimezone().utcoffset() == timedelta(hours=8):
        return "zh"
    return "en"


LANG = detect_lang()

STR = {
    "zh": {
        "no_title": "(无标题)",
        "just_now": "刚刚",
        "min_ago": "{n}分钟前",
        "hour_ago": "{n}小时前",
        "day_ago": "{n}天前",
        "no_sessions_page": "（本页没有会话）",
        "h_index": "#",
        "h_time": "时间",
        "h_topic": "主题",
        "h_project": "项目",
        "h_session": "会话ID",
        "h_turns": "轮次",
        "idx_oob": "序号 {idx} 超出范围（1-{total}）。",
        "id_ambiguous": "{n} 个会话的 ID 以 '{query}' 开头，请多给几位字符。",
        "kw_header": "多个会话匹配该关键词，请用序号或会话ID指定：",
        "kw_none": "没有会话匹配 '{query}'。",
        "all_projects": "全部项目",
        "project_named": "项目 {name}",
        "list_title": "## 最近的历史会话 · {scope} · 第 {page}/{pages} 页 · 共 {total} 条",
        "empty_scope": "当前范围没有历史会话。",
        "reply_index": "回复**序号**即可接上对应会话（会给出 /resume 命令）。",
        "next_page": "想看更早的会话，说“下一页”或运行 `--page {page}`。",
        "last_page": "已是最后一页（第 {pages} 页）。",
        "hidden_hint": "已隐藏 {n} 条无意义主题（hello / 上一页 / 下一页 / (无标题)），如果需要全部显示请回复「全部显示」。",
        "no_sessions": "没有找到任何历史会话。",
        "label_session": "会话：{topic}",
        "label_time_project_id": "时间：{time}    项目：{cwd}    ID：{sid}",
        "label_project_id": "项目：{cwd}    ID：{sid}",
        "choose_one": "接上这个会话，二选一：",
        "resume_same_1": "  1) 当前会话内直接切换：   /resume {sid}",
        "resume_same_2": "  2) 退出后在终端运行：     claude --resume {sid}",
        "resume_other_1": "  1) 该会话属于其它项目目录 {cwd}，需先进入该目录再 resume：",
        "resume_other_2": "  2) 或在那个目录下运行的会话里使用：/resume {sid}",
        "if_not_opened": "   （若没弹出，在新终端里手动运行：{cmd}）",
        "opened_tmux": "已在 tmux 新窗口打开",
        "opened_wt": "已在 Windows Terminal 新窗口打开",
        "opened_cmd": "已在新 cmd 窗口打开",
        "opened_term": "已新开终端窗口并接上会话",
        "open_failed": "自动开窗失败，请手动运行下面的命令",
        "open_unsupported": "当前环境不支持自动开窗，请手动运行下面的命令",
        "osascript_failed": "osascript 执行失败（可能需要在系统设置里授予“自动化”权限）",
        "cli_desc": "列出 Claude Code 历史会话主题，并生成接上会话的命令。",
        "cli_lang": "输出语言：zh 或 en（覆盖自动检测）",
        "cli_list": "列出历史会话（默认命令）",
        "cli_current": "只看当前目录的会话（默认跨所有项目）",
        "cli_project": "指定项目目录",
        "cli_limit": "每页显示多少条（默认 20）",
        "cli_page": "页码，从 1 开始（默认 1）",
        "cli_grep": "按关键词过滤主题",
        "cli_all": "显示全部，不过滤 hello/上一页/下一页/(无标题) 等无意义主题",
        "cli_all_short": "包含被过滤的无意义主题",
        "cli_json": "输出本页 JSON",
        "cli_resume": "为指定会话生成 resume 命令（粘贴用）",
        "cli_launch": "新开终端窗口并自动接上指定会话",
        "cli_query": "序号、会话ID 前缀或关键词",
        "cli_current_find": "只在当前目录查找",
        "cli_print": "只打印命令，不真正开窗",
    },
    "en": {
        "no_title": "(untitled)",
        "just_now": "just now",
        "min_ago": "{n}m ago",
        "hour_ago": "{n}h ago",
        "day_ago": "{n}d ago",
        "no_sessions_page": "(no sessions on this page)",
        "h_index": "#",
        "h_time": "Time",
        "h_topic": "Topic",
        "h_project": "Project",
        "h_session": "Session",
        "h_turns": "Turns",
        "idx_oob": "Index {idx} is out of range (1-{total}).",
        "id_ambiguous": "{n} sessions start with id '{query}'; give more characters.",
        "kw_header": "Multiple sessions match that keyword; pick one by index or session id:",
        "kw_none": "No session matches '{query}'.",
        "all_projects": "All projects",
        "project_named": "Project {name}",
        "list_title": "## Recent sessions · {scope} · Page {page}/{pages} · {total} total",
        "empty_scope": "No sessions in this scope.",
        "reply_index": "Reply with the **index** to resume a session (a /resume command is shown).",
        "next_page": "For older sessions, say \"next page\" or run `--page {page}`.",
        "last_page": "This is the last page (page {pages}).",
        "hidden_hint": "Hidden {n} noise sessions (hello / previous page / next page / untitled). Reply \"show all\" to list everything.",
        "no_sessions": "No sessions found.",
        "label_session": "Session: {topic}",
        "label_time_project_id": "Time: {time}    Project: {cwd}    ID: {sid}",
        "label_project_id": "Project: {cwd}    ID: {sid}",
        "choose_one": "Resume this session — pick one:",
        "resume_same_1": "  1) Switch in this session:   /resume {sid}",
        "resume_same_2": "  2) Run in a terminal:         claude --resume {sid}",
        "resume_other_1": "  1) This session lives in {cwd}; enter that directory first:",
        "resume_other_2": "  2) Or from a session running there: /resume {sid}",
        "if_not_opened": "   (if no window appeared, run manually in a new terminal: {cmd})",
        "opened_tmux": "Opened a new tmux window",
        "opened_wt": "Opened a new Windows Terminal window",
        "opened_cmd": "Opened a new cmd window",
        "opened_term": "Opened a new terminal window and resumed the session",
        "open_failed": "Auto-open failed; run the command below manually",
        "open_unsupported": "Auto-open is not supported here; run the command below manually",
        "osascript_failed": "osascript failed (grant the “Automation” permission in System Settings)",
        "cli_desc": "List Claude Code sessions with their topics and build resume commands.",
        "cli_lang": "Output language: zh or en (overrides auto-detection)",
        "cli_list": "List sessions (the default command)",
        "cli_current": "Only sessions in the current directory (default: all projects)",
        "cli_project": "Restrict to a project directory",
        "cli_limit": "Rows per page (default 20)",
        "cli_page": "Page number, starting at 1 (default 1)",
        "cli_grep": "Filter topics by keyword",
        "cli_all": "Show everything, including hello/previous page/next page/(untitled) noise topics",
        "cli_all_short": "Include the filtered-out noise topics",
        "cli_json": "Print this page as JSON",
        "cli_resume": "Print the resume command for a session (to paste)",
        "cli_launch": "Open a new terminal window and resume a session",
        "cli_query": "Index, session-id prefix, or keyword",
        "cli_current_find": "Search only the current directory",
        "cli_print": "Only print the command, do not open a window",
    },
}


def t(key: str, **kw) -> str:
    return STR[LANG][key].format(**kw)


# Topics that carry no signal about what a session was about: the title was
# never generated, the user only typed hello/hi, or they were just paginating
# this very tool with 上一页/下一页 (previous page / next page). Both languages
# are recognized so a machine's language settings never leak sessions in.
NOISE_TOPICS = {
    "(无标题)", "(untitled)", "hello", "hi",
    "上一页", "下一页", "previous page", "prev page", "next page",
}
_NOISE_LC = {x.lower() for x in NOISE_TOPICS}


def is_noise_topic(topic: str) -> bool:
    return topic.strip().lower() in _NOISE_LC

# Slash commands that are pure UI/plumbing: their args ("/resume interview")
# describe what the user was trying to do, never the session's topic.
BUILTIN_COMMANDS = {
    "/resume", "/exit", "/quit", "/clear", "/compact", "/help", "/login",
    "/logout", "/model", "/config", "/status", "/vim", "/doctor", "/cost",
    "/bug", "/release-notes", "/privacy-settings", "/terminal-setup",
}


def encode_cwd(path: str) -> str:
    return _ENCODE_RE.sub("-", os.path.abspath(path))


def clean_text(text: str, limit: int = 80) -> str:
    """Strip slash-command wrappers and XML noise, collapse whitespace.

    For a slash command like ``/skill-creator do the thing`` we keep the args
    (the meaningful part) but drop the redundant command-name/message text.
    """
    text = LOCAL_CMD_RE.sub(" ", text)
    text = COMMAND_TAG_RE.sub(" ", text)
    text = COMMAND_ARGS_TAG_RE.sub(" ", text)
    text = ANY_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def is_meaningful(text: str) -> bool:
    """Does this read like a real topic, rather than prompt noise?

    Filters the kinds of strings that pollute a topic when a session has no
    ai-title: the bare "9"/"7"/"1" a user types to pick a session from this
    very tool, lone punctuation, and the boilerplate a skill injects.
    """
    t = text.strip()
    if len(t) < 2:
        return False
    if not re.search(r"[A-Za-z一-鿿]", t):
        return False  # pure digits / punctuation, nothing to say
    if UUID_RE.fullmatch(t):
        return False  # a bare session id, e.g. left over from "/resume <id>"
    if t.startswith("Base directory for this skill"):
        return False
    return True


def is_builtin_command(raw: str) -> bool:
    """True if the message is just a built-in slash command (its args are noise)."""
    m = COMMAND_NAME_RE.search(raw)
    return bool(m and m.group(1).lower() in BUILTIN_COMMANDS)


def extract_topic_preview(block) -> str:
    """Pull plain text out of a user message content that may be str or list."""
    if isinstance(block, str):
        return block
    if isinstance(block, list):
        for part in block:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text", "")
    return ""


def parse_session(path: Path):
    """Read one transcript and return a summary dict, or None if unusable."""
    session_id = path.stem
    cwd = None
    ai_title = None
    last_prompt = None
    first_user_prompt = None
    first_ts = None
    last_ts = None
    turns = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rtype = rec.get("type")
                if cwd is None and rec.get("cwd"):
                    cwd = rec["cwd"]

                ts = rec.get("timestamp")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                if rtype == "ai-title":
                    title = rec.get("aiTitle")
                    if title:
                        ai_title = title
                elif rtype == "last-prompt":
                    lp = rec.get("lastPrompt")
                    if lp:
                        last_prompt = lp
                elif rtype in ("user", "assistant"):
                    if rec.get("isSidechain"):
                        continue
                    if rtype == "user":
                        msg = rec.get("message", {})
                        content = msg.get("content")
                        # Tool results are 'user' records too; skip them when
                        # hunting for the human's first real prompt.
                        is_tool_result = isinstance(content, list) and any(
                            isinstance(p, dict) and p.get("type") == "tool_result"
                            for p in content
                        )
                        if not is_tool_result and not rec.get("isMeta"):
                            raw = extract_topic_preview(content)
                            if raw and "<local-command" not in raw and not is_builtin_command(raw):
                                cleaned = clean_text(raw)
                                if cleaned and is_meaningful(cleaned) and first_user_prompt is None:
                                    first_user_prompt = cleaned
                    turns += 1
    except OSError:
        return None

    if cwd is None:
        # Fall back to decoding the parent directory name.
        cwd = path.parent.name

    last_prompt_clean = clean_text(last_prompt) if last_prompt else None
    # Prefer the AI title; fall back to the first real user prompt (the best
    # proxy for why the session exists), and only last-resort to the latest
    # prompt — which is often just the "9" a user typed to pick a session here.
    topic = ai_title or first_user_prompt or (
        last_prompt_clean if last_prompt_clean and is_meaningful(last_prompt_clean) else None
    ) or ""
    return {
        "session_id": session_id,
        "cwd": cwd,
        "ai_title": ai_title,
        "first_prompt": first_user_prompt,
        "last_prompt": last_prompt_clean,
        "topic": clean_text(topic, limit=100) or t("no_title"),
        "turns": turns,
        "started_at": first_ts,
        "last_at": last_ts,
        "mtime": path.stat().st_mtime,
        "path": str(path),
    }


def load_sessions(project_filter: str | None, show_all: bool = False):
    """Return (sessions, hidden_count), newest first.

    project_filter is a cwd to match. Unless show_all, sessions whose topic is
    pure noise (no-title / hello / 上一页 / 下一页) are dropped and counted, so
    callers can tell the user how many were hidden.
    """
    pattern = str(PROJECTS_DIR / "*" / "*.jsonl")
    sessions = []
    hidden = 0
    for f in glob.glob(pattern):
        info = parse_session(Path(f))
        if not info:
            continue
        if project_filter is not None:
            if os.path.abspath(info["cwd"]) != os.path.abspath(project_filter):
                continue
        if not show_all and is_noise_topic(info["topic"]):
            hidden += 1
            continue
        sessions.append(info)

    # A session that changed working directory mid-conversation is written to
    # more than one project dir, so the same sessionId can show up twice. Keep
    # the most recently active copy.
    def sort_key(s):
        return s["last_at"] or s["mtime"]

    deduped = {}
    for s in sessions:
        prev = deduped.get(s["session_id"])
        if prev is None or sort_key(s) > sort_key(prev):
            deduped[s["session_id"]] = s
    sessions = list(deduped.values())

    sessions.sort(key=sort_key, reverse=True)
    return sessions, hidden


def human_time(iso_ts: str | None, mtime: float) -> str:
    """Render a compact relative time like '3小时前' or '2026-10-08 14:00'."""
    dt = None
    if iso_ts:
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None:
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (now - dt).total_seconds()
    if delta < 60:
        return t("just_now")
    if delta < 3600:
        return t("min_ago", n=int(delta // 60))
    if delta < 86400:
        return t("hour_ago", n=int(delta // 3600))
    if delta < 86400 * 7:
        return t("day_ago", n=int(delta // 86400))
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def short_cwd(cwd: str) -> str:
    return Path(cwd).name or cwd


def print_table(sessions, show_project: bool, start_index: int = 1):
    if not sessions:
        print(t("no_sessions_page"))
        return
    headers = [t("h_index"), t("h_time"), t("h_topic")]
    if show_project:
        headers.append(t("h_project"))
    headers += [t("h_session"), t("h_turns")]
    rows = []
    for offset, s in enumerate(sessions):
        row = [str(start_index + offset), human_time(s["last_at"], s["mtime"]), s["topic"]]
        if show_project:
            row.append(s["cwd"])
        row += [s["session_id"][:8], str(s["turns"])]
        rows.append(row)

    # Markdown table: renders cleanly in Claude Code and in a browser.
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        print("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |")


def resolve(sessions, query: str):
    """Find the session the user means. query may be an index, id prefix, or keyword."""
    query = query.strip()
    if query.isdigit():
        idx = int(query)
        if 1 <= idx <= len(sessions):
            return sessions[idx - 1], None
        return None, t("idx_oob", idx=idx, total=len(sessions))

    low = query.lower()
    id_matches = [s for s in sessions if s["session_id"].startswith(low)]
    if len(id_matches) == 1:
        return id_matches[0], None
    if len(id_matches) > 1:
        return None, t("id_ambiguous", n=len(id_matches), query=query)

    kw_matches = [
        s for s in sessions
        if low in s["topic"].lower()
        or (s["first_prompt"] and low in s["first_prompt"].lower())
        or (s["last_prompt"] and low in s["last_prompt"].lower())
    ]
    if len(kw_matches) == 1:
        return kw_matches[0], None
    if len(kw_matches) > 1:
        lines = [t("kw_header")]
        for m in kw_matches[:10]:
            lines.append(f"  {m['session_id'][:8]}  {m['topic']}")
        return None, "\n".join(lines)

    return None, t("kw_none", query=query)


def cmd_list(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions, hidden = load_sessions(project_filter, show_all=args.show_all)

    if args.grep:
        low = args.grep.lower()
        sessions = [
            s for s in sessions
            if low in s["topic"].lower()
            or (s["first_prompt"] and low in s["first_prompt"].lower())
            or (s["last_prompt"] and low in s["last_prompt"].lower())
        ]

    total = len(sessions)
    page_size = args.limit or 20
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, args.page), pages)
    start = (page - 1) * page_size
    window = sessions[start:start + page_size]

    if args.json:
        print(json.dumps(window, ensure_ascii=False, indent=2))
        return 0

    scope = t("all_projects") if project_filter is None else t("project_named", name=short_cwd(project_filter))
    print(t("list_title", scope=scope, page=page, pages=pages, total=total))
    print()
    print_table(window, show_project=(project_filter is None), start_index=start + 1)
    print()
    if total == 0:
        print(t("empty_scope"))
    else:
        print(t("reply_index"))
        if page < pages:
            print(t("next_page", page=page + 1))
        elif page > 1:
            print(t("last_page", pages=pages))
    if hidden and not args.show_all:
        print(t("hidden_hint", n=hidden))
    return 0


def cmd_resume(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions, _ = load_sessions(project_filter, show_all=args.show_all)
    if not sessions:
        print(t("no_sessions"), file=sys.stderr)
        return 1
    target, err = resolve(sessions, args.query)
    if err:
        print(err, file=sys.stderr)
        return 1

    in_project = os.path.abspath(target["cwd"]) == os.path.abspath(os.getcwd())
    print(t("label_session", topic=target["topic"]))
    print(t("label_time_project_id",
            time=human_time(target["last_at"], target["mtime"]),
            cwd=target["cwd"], sid=target["session_id"]))
    print()
    print(t("choose_one"))
    if in_project:
        print(t("resume_same_1", sid=target["session_id"]))
        print(t("resume_same_2", sid=target["session_id"]))
    else:
        print(t("resume_other_1", cwd=target["cwd"]))
        print(f"     cd {target['cwd']} && claude --resume {target['session_id']}")
        print(t("resume_other_2", sid=target["session_id"]))
    return 0


def shell_resume_command(cwd: str, session_id: str) -> str:
    # Windows cmd/PowerShell 不认 POSIX 单引号，用双引号包裹路径。
    if sys.platform == "win32":
        return f'cd /d "{cwd}" && claude --resume {session_id}'
    return f"cd {shlex.quote(cwd)} && claude --resume {session_id}"


def _applescript_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_in_terminal(cwd: str, session_id: str) -> tuple[bool, str]:
    """Spawn a new terminal window/tab that runs `claude --resume <id>`.

    Returns (ok, message). This is how we make "type a number" actually resume
    a session: we can't take over the current terminal from inside Claude Code
    (no TTY), so we ask the OS to open a fresh one for us.
    """
    shell_cmd = shell_resume_command(cwd, session_id)

    # Inside tmux, a new window is the most natural and needs no OS automation.
    if os.environ.get("TMUX") and shutil.which("tmux"):
        r = subprocess.run(["tmux", "new-window", "-c", cwd, f"claude --resume {session_id}"],
                           capture_output=True, text=True)
        return (r.returncode == 0, r.stderr.strip() or t("opened_tmux"))

    # Windows：优先 Windows Terminal（wt），它能直接指定起始目录。
    if sys.platform == "win32":
        resume = f"claude --resume {session_id}"
        if shutil.which("wt"):
            # `cmd /k` 让窗口在 claude 退出后仍保留，便于看报错。
            r = subprocess.run(["wt", "-d", cwd, "cmd", "/k", resume],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return True, t("opened_wt")
        # 退回经典 cmd：用 CREATE_NEW_CONSOLE 开新窗口，起始目录直接由进程的
        # cwd 设定（跨盘符也没问题），避免 `start` + `cd` 的嵌套引号被 cmd 曲解。
        try:
            subprocess.Popen(["cmd", "/k", resume],
                             cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True, t("opened_cmd")
        except OSError as e:
            return False, (str(e) or t("open_failed"))

    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False, t("open_unsupported")

    term = os.environ.get("TERM_PROGRAM", "")
    if term == "iTerm.app":
        script = (
            'tell application "iTerm"\n'
            "activate\n"
            "tell current window\n"
            "create tab with default profile\n"
            f"tell current session to write text {_applescript_quote(shell_cmd)}\n"
            "end tell\n"
            "end tell"
        )
    else:
        script = (
            'tell application "Terminal"\n'
            "activate\n"
            f"do script {_applescript_quote(shell_cmd)}\n"
            "end tell"
        )

    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode == 0:
        return True, t("opened_term")
    return False, (r.stderr.strip() or t("osascript_failed"))


def cmd_launch(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions, _ = load_sessions(project_filter, show_all=args.show_all)
    if not sessions:
        print(t("no_sessions"), file=sys.stderr)
        return 1
    target, err = resolve(sessions, args.query)
    if err:
        print(err, file=sys.stderr)
        return 1

    print(t("label_session", topic=target["topic"]))
    print(t("label_project_id", cwd=target["cwd"], sid=target["session_id"]))

    if args.print_only:
        print()
        print(shell_resume_command(target["cwd"], target["session_id"]))
        return 0

    ok, msg = open_in_terminal(target["cwd"], target["session_id"])
    print()
    if ok:
        print(f"✅ {msg}")
        print(t("if_not_opened", cmd=shell_resume_command(target["cwd"], target["session_id"])))
        return 0
    print(f"⚠️ {msg}")
    print(shell_resume_command(target["cwd"], target["session_id"]))
    return 1


def build_parser():
    p = argparse.ArgumentParser(description=t("cli_desc"))
    p.add_argument("--lang", choices=("zh", "en"), help=t("cli_lang"))
    sub = p.add_subparsers(dest="command")

    pl = sub.add_parser("list", help=t("cli_list"))
    pl.add_argument("--current", action="store_true", help=t("cli_current"))
    pl.add_argument("--project", help=t("cli_project"))
    pl.add_argument("-n", "--limit", type=int, help=t("cli_limit"))
    pl.add_argument("-p", "--page", type=int, default=1, help=t("cli_page"))
    pl.add_argument("--grep", help=t("cli_grep"))
    pl.add_argument("--all", dest="show_all", action="store_true", help=t("cli_all"))
    pl.add_argument("--json", action="store_true", help=t("cli_json"))
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("resume", help=t("cli_resume"))
    pr.add_argument("query", help=t("cli_query"))
    pr.add_argument("--current", action="store_true", help=t("cli_current_find"))
    pr.add_argument("--project", help=t("cli_project"))
    pr.add_argument("--all", dest="show_all", action="store_true", help=t("cli_all_short"))
    pr.set_defaults(func=cmd_resume)

    pln = sub.add_parser("launch", help=t("cli_launch"))
    pln.add_argument("query", help=t("cli_query"))
    pln.add_argument("--current", action="store_true", help=t("cli_current_find"))
    pln.add_argument("--project", help=t("cli_project"))
    pln.add_argument("--all", dest="show_all", action="store_true", help=t("cli_all_short"))
    pln.add_argument("--print", dest="print_only", action="store_true", help=t("cli_print"))
    pln.set_defaults(func=cmd_launch)

    return p


def _take_lang_flag(argv):
    """Pull out a `--lang zh|en` flag, set global LANG, return the rest.

    Done before the parser is built so both `--help` and the output honor it,
    and before the "default to list" step so `--lang en list` isn't mangled.
    """
    global LANG
    out = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        val = None
        consumed = 1
        if tok == "--lang" and i + 1 < len(argv):
            val = argv[i + 1]
            consumed = 2
        elif tok.startswith("--lang="):
            val = tok.split("=", 1)[1]
        if val in ("zh", "en"):
            LANG = val
            i += consumed
            continue
        out.append(tok)
        i += 1
    return out


def main(argv=None):
    argv = _take_lang_flag(list(sys.argv[1:] if argv is None else argv))
    # Default to `list` when no subcommand is given.
    if not argv or argv[0].startswith("-"):
        argv = ["list"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
