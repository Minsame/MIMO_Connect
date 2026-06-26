# MIMO_Connect Context

MIMO_Connect is a voice/chat middleware that lets a chat platform control a local coding CLI, currently MiMo Code.

## 自主闭环（铁律）

默认自行完成闭环：读取代码 → 理解机制 → 学习现有逻辑 → 修改 → 测试 → 读错纠正 → 再测试 → 确认无误后交付。遇到问题先自己深入读源码和日志去定位，能改就改、改完就验证，错了就继续更正，不要一有疑问就停下来问用户。

仅在以下两种情况才停下来询问用户：
1. 已经充分了解相关机制（读过代码、日志、相关文档）后仍然无法解决；
2. 操作可能高危（如删除/修改用户文件或 MiMo Code 数据、重置 git、动到会破坏 session 恢复或线上凭证的逻辑）。

除此之外，按上面的良性循环自主推进到交付。

## 回复语言（铁律）

始终用简体中文回复用户，禁止中途切换为英文/日文或其他语言。代码、命令、标识符等专有名词可保留原文，叙述性文字一律中文。

## 测试（铁律）

每次代码修改后必须跑一次全量测试：`python -m pytest tests/ -q`（项目根 `pytest.ini` 已设 `asyncio_mode = auto`）。全绿才算改动完成。

## Language

**Platform**: The chat adapter that receives user messages and sends replies. Current adapters: Feishu and Weixin.

**Agent**: The coding assistant adapter behind the middleware. Current agent: MiMo Code CLI.

**Engine**: The central orchestrator in `core/engine.py`. It routes platform messages, middleware commands, intent classification, agent events, voice generation, and replies.

**User-visible text**: MiMo Code output intended for the user. In `mimo run --format json`, this is primarily `type=text` with `part.text`.

**Internal event**: MiMo Code execution metadata such as `step_start`, `step_finish`, `tool_use`, `tool_result`, `thinking`, and `reasoning`. These should not be sent to chat as normal replies.

**Permission request**: A MiMo Code request to access a path outside its current working directory, often emitted on stderr as `permission requested: external_directory (...)`.

**Detail mode**: Middleware mode toggled by `/show`. It aggregates user-visible MiMo text every 3 seconds.

**Hidden mode**: Middleware mode toggled by `/hide`. It sends only the opening user-visible text and final user-visible reply.

**Voice replay**: Middleware-only action where the user asks to read the previous reply aloud. It should not be forwarded to MiMo Code.

## Relationships

- A Platform sends `Message` objects to the Engine.
- The Engine may handle middleware commands directly, or classify intent through the intent router.
- Code tasks are sent to the Agent.
- The Agent emits events back to the Engine.
- The Engine filters internal events, stores status, detects options/permissions, and sends `Reply` objects through the Platform.
- Voice output is optional and should not be auto-generated for rich text unless explicitly requested.

## Design constraints

- Preserve rich text formatting for code blocks, tables, and markdown.
- Do not expose tool call details or file modification internals to chat users.
- Do not use `--dangerously-skip-permissions` for ordinary authorization.
- Prefer starting MiMo Code in the authorized project directory over granting broad permissions.
- Middleware commands such as `/show`, `/hide`, progress queries, and voice replay must be handled before LLM intent classification.
- Tests and probes should use deterministic CLI invocations when possible.
- The middleware should not reinterpret or rewrite normal user intent for MiMo Code; MiMo is itself an LLM and should receive the user's original instruction whenever possible.
- The middleware's role is adaptation: route MiMo native option/permission prompts to the chat platform, pass user selections or free-text responses back through the correct Agent path, preserve structure such as options/tables/code blocks, and filter internal CLI events from user-visible replies.

## Historical context

历史改动、架构决策、坑点、未完成事项已迁出到分层项目记忆，按需检索：

- `memory/projects/Voice_Coding_MW/decisions.md` — 架构决策与已落地改动（按时间倒序）
- `memory/projects/Voice_Coding_MW/gotchas.md` — 坑点与失败模式
- `memory/projects/Voice_Coding_MW/tasks.md` — 跨会话未完成事项
- `memory/projects/Voice_Coding_MW/structure.md` / `workflows.md` / `project.md` — 结构、流程、总览

召回方式：`memory({operation:"search", query:"<keyword>"})` 或直接 Read 上述文件。
