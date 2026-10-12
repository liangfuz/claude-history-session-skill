---
name: claude-history-session
description: 列出并接上 Claude Code 的历史会话。当用户想回顾之前聊过的对话、找回某个会话、接上之前在别的终端或项目里的会话，或者问"我们上次聊到哪了""之前的对话""历史会话""继续之前的会话""上次那个聊某事的会话"时使用。用户关掉终端重开、换了目录、过了一段时间想接着之前聊时也应主动使用。只要用户流露出想找回或继续一段旧的 Claude Code 对话的意图，即使没说"历史会话"这几个字，也要使用本技能。
---

# Claude Code 历史会话

## 这个技能解决什么

用户关掉终端、重开窗口或换了目录后，常常想不起之前那个会话在聊什么、叫什么，也就无从用 `/resume` 找回。本技能读取 Claude Code 落在磁盘上的会话记录，按时间倒序列出最近的会话主题，并给出**可直接执行的接上命令**。

产出不是渲染完整对话，而是一份能一眼看懂的**会话主题清单**——用户看到主题就知道要接哪一段。

## 数据来源

Claude Code 把每个会话的完整记录写在 `~/.claude/projects/<编码后的cwd>/<sessionId>.jsonl`，每行一条 JSON。关键记录类型：

- `ai-title` — Claude 为会话生成的短标题，**这就是最理想的"主题"**
- `last-prompt` — 该会话最近一次的提问
- `user` / `assistant` — 对话轮次（`isSidechain=true` 的是子 agent，需跳过）

同一会话若中途换了工作目录，可能同时存在于两个项目目录下——脚本已按 `sessionId` 去重，保留最新的一份。

## 默认行为

用户调用本技能时，**直接运行脚本、原样展示结果**，不要先反问：

```bash
python3 scripts/session_history.py
```

（脚本路径相对本技能目录；不确定时用绝对路径 `~/.claude/skills/claude-history-session/scripts/session_history.py`。）

默认输出：**跨所有项目**、按最近活跃时间**倒序**、**每页 20 条**，带全局序号。展示后，脚本会自动附上"回复序号即可接上"的提示。

## 工作流

1. 用户说"看历史对话""接上上次那个"之类时，运行默认命令，把表格**原样呈现**给用户。
2. 等用户**回复序号**（如"3"）。用户也可能说关键词（"就是那个聊 WMS 的"）或会话 ID 前缀。
3. **回复序号后，不要只给命令让用户去复制——直接帮他把会话开起来**，用 `launch`：

   ```bash
   python3 scripts/session_history.py launch <会话ID前缀>   # 自动新开终端窗口并接上
   ```

   `launch` 会新开一个终端窗口（macOS Terminal / iTerm；在 tmux 里则开新 tmux 窗口）并执行
   `cd <会话目录> && claude --resume <会话ID>`，用户无需手动拷贝粘贴。

   **优先传会话 ID 前缀而不是序号**：会话列表是实时变化的（别处新建的会话会插进来），
   序号可能在展示与执行之间漂移；而从你刚才展示的表格里取到的**会话ID 前缀**是稳定的。
   所以看到用户回复"3"，就去表格第 3 行取出它的 8 位会话ID，再 `launch <那8位>`。
4. 如果用户明确说"我只要命令，自己粘"（或环境不支持自动开窗），改用 `resume` 子命令，
   它只打印命令不动手：

   ```bash
   python3 scripts/session_history.py resume <会话ID前缀>   # 只打印接上命令
   python3 scripts/session_history.py launch <ID> --print   # 只打印将要执行的命令，不开窗
   ```

   自己粘贴时，接上方式有两种：
   - **当前会话内切换（首选）**：输入 `/resume <sessionId>`——Claude Code 内置支持，无需退出。
   - **退出后重开**：`claude --resume <sessionId>`；若会话属于别的项目目录，先 `cd <该目录>`。
5. 若关键词匹配到多个，脚本会列出候选，请用户挑一个再跑一次。

## 自动开窗的原理与边界

脚本本身在 Claude Code 里运行，拿不到终端 TTY，**无法接管你当前这个窗口**。所以"自动接上"
的做法是让系统打开一个**新**终端窗口去跑 resume 命令。各平台策略：

- **tmux 内**：`tmux new-window`，最干净，跨平台。
- **macOS**：`osascript` 驱动 Terminal / iTerm 开新窗口。首次使用若报权限错误，是 macOS 的
  "自动化"权限未授予：系统设置 → 隐私与安全性 → 自动化，允许 Terminal 控制 Terminal。
- **Windows**：优先 Windows Terminal（`wt -d <目录> cmd /k ...`），没装则退回 `cmd /c start`
  开经典 cmd 窗口。两者都用 `cmd /k` 让窗口在 claude 退出后保留，便于看报错。

当前窗口的会话不受影响，两边可以并存。若以上都不适用（或自动开窗失败），`launch` 会退回为
**打印命令**让用户手动执行——回退命令已按平台适配：macOS/Linux 用 `shlex.quote` 的单引号写法，
Windows 用 `cd /d "..."`，可直接粘进 cmd / PowerShell。

## 翻页与筛选

会话很多时默认只显示最近 20 条。用户想看得更早就翻页：

```bash
python3 scripts/session_history.py list --page 2      # 第 2 页（#21-40）
python3 scripts/session_history.py list --page 3 -n 30  # 第 3 页，每页 30 条
python3 scripts/session_history.py list --grep 部署     # 只留主题含"部署"的
python3 scripts/session_history.py list --current      # 只看当前目录
python3 scripts/session_history.py list --json         # 结构化输出
```

序号是**全局**的（跨页连续），所以第 2 页的 13 号对应的会话在前一页也能连续编号。
翻页后仍从**当前展示的表格**里取会话ID 再 `launch`，不要凭记忆用旧序号。

当用户说"下一页""更早的"时，就把页码加一重跑并展示。

## 为什么不做方向键选择

会话内运行的脚本拿不到终端 TTY（`/dev/tty` 不可用），无法提供上下键交互菜单。所以选择方式是**回复序号**。如果用户就是想要方向键，提示他们直接输入 `/resume`（不带参数）打开 Claude Code 原生的交互式选择器。这一点如实说明，不要假装能弹菜单。

## 边界情况

- **当前会话本身**也会出现在列表里（排在最前），正常——用户可能只是想确认现在在哪个会话。
- **跨项目会话**：`/resume <id>` 在部分版本按当前目录过滤，所以对别的项目的会话，优先给 `cd <目录> && claude --resume <id>`。
- 主题为空（会话只跑过 `/clear`、`/resume` 这类本地命令）时显示 `(无标题)`，这是预期的。
- 列表里出现 `hello`、`(无标题)` 这类平淡主题，通常是测试性会话，无需特别处理。
