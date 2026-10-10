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
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
PROJECTS_DIR = CLAUDE_DIR / "projects"

COMMAND_TAG_RE = re.compile(r"<command-(?:name|message)>.*?</command-(?:name|message)>", re.S)
COMMAND_ARGS_TAG_RE = re.compile(r"</?command-args>")
LOCAL_CMD_RE = re.compile(r"<local-command[^>]*>.*?</local-command[^>]*>", re.S)
ANY_TAG_RE = re.compile(r"<[^>]+>")


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
                            if raw and "<local-command" not in raw:
                                cleaned = clean_text(raw)
                                if cleaned and first_user_prompt is None:
                                    first_user_prompt = cleaned
                    turns += 1
    except OSError:
        return None

    if cwd is None:
        # Fall back to decoding the parent directory name.
        cwd = path.parent.name

    topic = ai_title or last_prompt or first_user_prompt or ""
    return {
        "session_id": session_id,
        "cwd": cwd,
        "ai_title": ai_title,
        "first_prompt": clean_text(first_user_prompt) if first_user_prompt else None,
        "last_prompt": clean_text(last_prompt) if last_prompt else None,
        "topic": clean_text(topic, limit=100) or "(无标题)",
        "turns": turns,
        "started_at": first_ts,
        "last_at": last_ts,
        "mtime": path.stat().st_mtime,
        "path": str(path),
    }


def load_sessions(project_filter: str | None):
    """Return all sessions, newest first. project_filter is a cwd to match."""
    pattern = str(PROJECTS_DIR / "*" / "*.jsonl")
    sessions = []
    for f in glob.glob(pattern):
        info = parse_session(Path(f))
        if not info:
            continue
        if project_filter is not None:
            if os.path.abspath(info["cwd"]) != os.path.abspath(project_filter):
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
    return sessions


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
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)}分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)}小时前"
    if delta < 86400 * 7:
        return f"{int(delta // 86400)}天前"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def short_cwd(cwd: str) -> str:
    return Path(cwd).name or cwd


def print_table(sessions, show_project: bool, start_index: int = 1):
    if not sessions:
        print("（本页没有会话）")
        return
    headers = ["#", "时间", "主题"]
    if show_project:
        headers.append("项目")
    headers += ["会话ID", "轮次"]
    rows = []
    for offset, s in enumerate(sessions):
        row = [str(start_index + offset), human_time(s["last_at"], s["mtime"]), s["topic"]]
        if show_project:
            row.append(short_cwd(s["cwd"]))
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
        return None, f"序号 {idx} 超出范围（1-{len(sessions)}）。"

    low = query.lower()
    id_matches = [s for s in sessions if s["session_id"].startswith(low)]
    if len(id_matches) == 1:
        return id_matches[0], None
    if len(id_matches) > 1:
        return None, f"{len(id_matches)} 个会话的 ID 以 '{query}' 开头，请多给几位字符。"

    kw_matches = [
        s for s in sessions
        if low in s["topic"].lower()
        or (s["first_prompt"] and low in s["first_prompt"].lower())
        or (s["last_prompt"] and low in s["last_prompt"].lower())
    ]
    if len(kw_matches) == 1:
        return kw_matches[0], None
    if len(kw_matches) > 1:
        lines = ["多个会话匹配该关键词，请用序号或会话ID指定："]
        for m in kw_matches[:10]:
            lines.append(f"  {m['session_id'][:8]}  {m['topic']}")
        return None, "\n".join(lines)

    return None, f"没有会话匹配 '{query}'。"


def cmd_list(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions = load_sessions(project_filter)

    if args.grep:
        low = args.grep.lower()
        sessions = [
            s for s in sessions
            if low in s["topic"].lower()
            or (s["first_prompt"] and low in s["first_prompt"].lower())
            or (s["last_prompt"] and low in s["last_prompt"].lower())
        ]

    total = len(sessions)
    page_size = args.limit or 10
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, args.page), pages)
    start = (page - 1) * page_size
    window = sessions[start:start + page_size]

    if args.json:
        print(json.dumps(window, ensure_ascii=False, indent=2))
        return 0

    scope = "全部项目" if project_filter is None else f"项目 {short_cwd(project_filter)}"
    print(f"## 最近的历史会话 · {scope} · 第 {page}/{pages} 页 · 共 {total} 条")
    print()
    print_table(window, show_project=(project_filter is None), start_index=start + 1)
    print()
    if total == 0:
        print("当前范围没有历史会话。可以试试 `--all` 查看所有项目。")
        return 0
    print(f"回复**序号**即可接上对应会话（会给出 /resume 命令）。")
    if page < pages:
        print(f"想看更早的会话，说“下一页”或运行 `--page {page + 1}`。")
    elif page > 1:
        print(f"已是最后一页（第 {pages} 页）。")
    return 0


def cmd_resume(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions = load_sessions(project_filter)
    if not sessions:
        print("没有找到任何历史会话。", file=sys.stderr)
        return 1
    target, err = resolve(sessions, args.query)
    if err:
        print(err, file=sys.stderr)
        return 1

    in_project = os.path.abspath(target["cwd"]) == os.path.abspath(os.getcwd())
    print(f"会话：{target['topic']}")
    print(f"时间：{human_time(target['last_at'], target['mtime'])}    项目：{target['cwd']}    ID：{target['session_id']}")
    print()
    print("接上这个会话，二选一：")
    if in_project:
        print(f"  1) 当前会话内直接切换：   /resume {target['session_id']}")
        print(f"  2) 退出后在终端运行：     claude --resume {target['session_id']}")
    else:
        print(f"  1) 该会话属于其它项目目录 {target['cwd']}，需先进入该目录再 resume：")
        print(f"     cd {target['cwd']} && claude --resume {target['session_id']}")
        print(f"  2) 或在那个目录下运行的会话里使用：/resume {target['session_id']}")
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
        return (r.returncode == 0, r.stderr.strip() or "已在 tmux 新窗口打开")

    # Windows：优先 Windows Terminal（wt），它能直接指定起始目录。
    if sys.platform == "win32":
        resume = f"claude --resume {session_id}"
        if shutil.which("wt"):
            # `cmd /k` 让窗口在 claude 退出后仍保留，便于看报错。
            r = subprocess.run(["wt", "-d", cwd, "cmd", "/k", resume],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return True, "已在 Windows Terminal 新窗口打开"
        # 退回经典 cmd：用 CREATE_NEW_CONSOLE 开新窗口，起始目录直接由进程的
        # cwd 设定（跨盘符也没问题），避免 `start` + `cd` 的嵌套引号被 cmd 曲解。
        try:
            subprocess.Popen(["cmd", "/k", resume],
                             cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True, "已在新 cmd 窗口打开"
        except OSError as e:
            return False, (str(e) or "自动开窗失败，请手动运行下面的命令")

    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False, "当前环境不支持自动开窗，请手动运行下面的命令"

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
        return True, "已新开终端窗口并接上会话"
    return False, (r.stderr.strip() or "osascript 执行失败（可能需要在系统设置里授予“自动化”权限）")


def cmd_launch(args):
    project_filter = args.project or (os.getcwd() if args.current else None)
    sessions = load_sessions(project_filter)
    if not sessions:
        print("没有找到任何历史会话。", file=sys.stderr)
        return 1
    target, err = resolve(sessions, args.query)
    if err:
        print(err, file=sys.stderr)
        return 1

    print(f"会话：{target['topic']}")
    print(f"项目：{target['cwd']}    ID：{target['session_id']}")

    if args.print_only:
        print()
        print(shell_resume_command(target["cwd"], target["session_id"]))
        return 0

    ok, msg = open_in_terminal(target["cwd"], target["session_id"])
    print()
    if ok:
        print(f"✅ {msg}")
        print(f"   （若没弹出，在新终端里手动运行：{shell_resume_command(target['cwd'], target['session_id'])}）")
        return 0
    print(f"⚠️ {msg}")
    print(shell_resume_command(target["cwd"], target["session_id"]))
    return 1


def build_parser():
    p = argparse.ArgumentParser(
        description="列出 Claude Code 历史会话主题，并生成接上会话的命令。",
    )
    sub = p.add_subparsers(dest="command")

    pl = sub.add_parser("list", help="列出历史会话（默认命令）")
    pl.add_argument("--current", action="store_true", help="只看当前目录的会话（默认跨所有项目）")
    pl.add_argument("--project", help="指定项目目录")
    pl.add_argument("-n", "--limit", type=int, help="每页显示多少条（默认 10）")
    pl.add_argument("-p", "--page", type=int, default=1, help="页码，从 1 开始（默认 1）")
    pl.add_argument("--grep", help="按关键词过滤主题")
    pl.add_argument("--json", action="store_true", help="输出本页 JSON")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("resume", help="为指定会话生成 resume 命令（粘贴用）")
    pr.add_argument("query", help="序号、会话ID 前缀或关键词")
    pr.add_argument("--current", action="store_true", help="只在当前目录查找")
    pr.add_argument("--project", help="指定项目目录")
    pr.set_defaults(func=cmd_resume)

    pln = sub.add_parser("launch", help="新开终端窗口并自动接上指定会话")
    pln.add_argument("query", help="序号、会话ID 前缀或关键词")
    pln.add_argument("--current", action="store_true", help="只在当前目录查找")
    pln.add_argument("--project", help="指定项目目录")
    pln.add_argument("--print", dest="print_only", action="store_true", help="只打印命令，不真正开窗")
    pln.set_defaults(func=cmd_launch)

    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Default to `list` when no subcommand is given.
    if not argv or argv[0].startswith("-"):
        argv = ["list"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
