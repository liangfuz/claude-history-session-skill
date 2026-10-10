# claude-history-session

> 关掉终端重开之后，一句话找回并接上之前的 Claude Code 会话。

`claude-history-session` 是一个 Claude Code 技能（Skill）：读取 Claude Code 落在磁盘上的会话记录，按时间倒序列出最近的会话主题，并**直接把选中的会话接上**——自动开一个新终端窗口跑 `claude --resume`，不用手动复制粘贴。

---

## 它解决什么问题

Claude Code 的会话都保存在本地，但想找回之前的那一段时却常常卡壳：

- 关掉终端、换了目录之后，不记得之前那个会话在聊什么、叫什么，也就无从 `/resume`；
- 原生的 `/resume` 选择器只列**当前目录**下的会话，跨项目的找不到；
- 即使找到了 sessionId，还要手动拼 `cd <目录> && claude --resume <id>`。

本技能把这三件事一次解决：**列主题 → 选一条 → 自动接上**。

---

## 效果预览

在 Claude Code 里说一句「看看我之前聊过什么」，它会自动列出最近的会话：

```
## 最近的历史会话 · 全部项目 · 第 1/7 页 · 共 32 条

| #  | 时间      | 主题                        | 项目                  | 会话ID   | 轮次 |
|----|-----------|-----------------------------|-----------------------|----------|------|
| 1  | 刚刚      | 修复登录接口的空指针        | user-service         | 4caec115 | 42   |
| 2  | 29分钟前  | WMS 库存对账脚本            | wms-account-script   | ee0450b8 | 15   |
| 3  | 2小时前   | 用 Python 写个预测补货接口  | forecast-py         | 249f8d16 | 35   |
| 4  | 昨天      | 梳理订单状态机设计          | order-service         | a28f3897 | 8    |
| 5  | 3天前     | (无标题)                    | scratch               | 3d31cee0 | 2    |

回复**序号**即可接上对应会话（会给出 /resume 命令）。
想看更早的会话，说“下一页”或运行 `--page 2`。
```

然后你只回一个序号，比如 `2`：

```
> 2
```

它就**自动新开一个终端窗口**，并已经在那个会话里了：

```
会话：WMS 库存对账脚本
项目：/Users/me/interview-prep-java    ID：ee0450b8-...

✅ 已在 tmux 新窗口打开
```

---

## 环境要求

| 项目 | 要求 |
|------|------|
| Claude Code | 已安装并能正常运行（需要 CLI；`claude` 在 PATH 里） |
| Python | **3.7+**（脚本用了 `from __future__ import annotations`，3.9 以下也能跑；推荐 3.9+） |
| 操作系统 | macOS / Linux / Windows 均可，但**自动开窗**能力各平台有差异，见下表 |

### 跨平台能力矩阵

| 功能 | macOS | Windows | Linux / tmux |
|------|:-----:|:-------:|:------------:|
| 列出历史会话（`list`） | ✅ | ✅ | ✅ |
| 会话内切换 `/resume <id>` | ✅ | ✅ | ✅ |
| 自动开新窗口接上（`launch`） | ✅ Terminal / iTerm | ✅ Windows Terminal / cmd | ✅ 仅 tmux 内 |

> 自动开窗不适用时，`launch` 会**优雅退化为打印命令**，不会报错，你把命令粘进终端即可。

---

## 安装

把整个目录放到 Claude Code 的 skills 目录下：

```bash
git clone https://github.com/<你的用户名>/claude-history-session.git \
  ~/.claude/skills/claude-history-session
```

Windows（PowerShell）：

```powershell
git clone https://github.com/<你的用户名>/claude-history-session.git `
  "$env:USERPROFILE\.claude\skills\claude-history-session"
```

装好后重启 Claude Code（或新开会话），技能即可被自动识别。无需其他依赖——脚本只用 Python 标准库。

---

## 使用方法

有两条路：**让 Claude 用技能**（推荐），或**直接跑脚本**。

### 方式一：在 Claude Code 里用自然语言触发

技能被触发后会自动展示列表，**你只需回一个序号**：

```
你 ▸ 看看我之前都聊过什么

Claude ▸ （自动列出最近 10 条会话主题，见上面的「效果预览」）

你 ▸ 2

Claude ▸ （自动新开终端窗口，接上第 2 条会话）
```

触发说法很随意，例如：

- 「上次聊 WMS 的那个会话，接上」
- 「我们上次聊到哪了？」
- 「找回之前那个写补丁的队伍」
- 直接输入 `/claude-history-session`

> **为什么是回序号、不是上下键选？**
> 脚本在 Claude Code 内运行，拿不到终端 TTY，无法弹交互式菜单。所以选择方式是**回复序号**。如果你确实想要方向键，直接在 Claude Code 里输入不带参数的 `/resume`，用原生选择器即可。

#### 翻页与筛选

会话多的时候，跟它说「下一页」「找含‘部署’的」即可。对应的底层命令：

```bash
python3 scripts/session_history.py list --page 2      # 第 2 页（#11-20）
python3 scripts/session_history.py list --page 3 -n 20 # 第 3 页，每页 20 条
python3 scripts/session_history.py list --grep 部署    # 只保留主题含“部署”的
```

### 方式二：直接运行脚本

不经过 Claude，自己在终端里跑也行（脚本路径相对本目录）：

```bash
# 默认：列出全部项目、最近 10 条、按时间倒序
python3 scripts/session_history.py

# 只看当前目录下的会话
python3 scripts/session_history.py --current

# 让某个会话自动开新窗口接上（传会话ID前缀或序号）
python3 scripts/session_history.py launch ee0450b8

# 只打印接上命令，不真开窗（自己复制粘贴用）
python3 scripts/session_history.py resume ee0450b8
python3 scripts/session_history.py launch ee0450b8 --print
```

#### 子命令与参数

| 命令 | 说明 |
|------|------|
| `list` | 列出历史会话（**默认命令**，不带子命令时即执行它） |
| `resume <查询>` | 解析出目标会话，**只打印**接上命令 |
| `launch <查询>` | 解析出目标会话，**新开终端窗口自动接上** |

`<查询>` 支持三种写法：**全局序号**（如 `2`）、**会话ID 前缀**（如 `ee0450b8`）、**主题关键词**（如 `WMS`）。

`list` 的常用参数：

| 参数 | 说明 |
|------|------|
| `--current` | 只看当前目录的项目（默认跨所有项目） |
| `--project <目录>` | 指定某个项目目录 |
| `-n, --limit <N>` | 每页显示条数（默认 10） |
| `-p, --page <N>` | 页码，从 1 开始 |
| `--grep <关键词>` | 按关键词过滤主题 |
| `--json` | 输出结构化的本页 JSON |

---

## 工作原理

Claude Code 把每个会话的完整记录写在：

```
~/.claude/projects/<编码后的cwd>/<sessionId>.jsonl
```

每行一条 JSON。脚本读取其中的关键记录来提炼「主题」：

- **`ai-title`** — Claude 为该会话生成的短标题，**首选**主题来源；
- **`last-prompt`** — 该会话最近一次的提问，次选；
- 若无上述，则回退到**第一条真实用户消息**（会跳过 `/clear`、`/resume` 这类本地命令，以及子 agent 的对话）。

其他处理：

- 同一会话若中途换过工作目录，会同时存在于两个项目目录下 —— 按 `sessionId` 去重，保留最新的一份；
- 时间按「最近活跃」倒序，展示为 `刚刚 / N分钟前 / N小时前 / N天前 / 绝对时间`；
- 会话目录可用环境变量 `CLAUDE_CONFIG_DIR` 覆盖（默认 `~/.claude`）。

---

## 常见问题

**Q：`launch` 报「当前环境不支持自动开窗」？**
说明你在非 macOS、且不在 tmux 里（Windows 已支持）。命令会被打印出来，直接粘贴执行即可。

**Q：macOS 首次自动开窗报权限错误？**
这是系统的「自动化」权限未授予：**系统设置 → 隐私与安全性 → 自动化**，允许 Terminal 控制 Terminal。

**Q：为什么不能用方向键选择？**
见上文「为什么是回序号」。脚本在无 TTY 环境运行，拿不到 `/dev/tty`。

**Q：列表里出现 `(无标题)` 或 `hello`？**
`(无标题)` 通常是只跑过 `/clear`、`/resume` 的会话；`hello` 之类的多是测试会话，可忽略。

**Q：会话属于别的项目目录，`/resume` 找不到？**
`/resume <id>` 在部分版本会按当前目录过滤。跨项目会话请先 `cd <该目录>`，或用 `launch`（它会自动带上正确的目录）。

---

## 目录结构

```
claude-history-session/
├── SKILL.md               # 技能定义（给 Claude 看的指令）
├── README.md              # 本文件
└── scripts/
    └── session_history.py # 核心脚本：解析会话、列主题、生成/执行接上命令
```

---

## 许可

MIT
