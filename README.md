# MIMO_Connect

让你在飞书 / 微信里用聊天或语音直接驱动本地的 MiMo Code CLI 编程。MIMO_Connect 是一个中间层：它接收聊天平台的消息，做意图识别与格式整理，转发给 MiMo Code 执行，再把结果（含可选语音）回送到聊天窗口。

## 核心功能

- **多平台接入**：飞书（WebSocket 长连接）、微信（iLink Bot）。
- **意图路由**：基于 LLM 的意图分类（默认 DeepSeek，支持 OpenAI / Anthropic / SiliconFlow / DashScope），区分编程任务、闲聊、确认、中断等。
- **MiMo Code 桥接**：解析 `mimo run --format json` 的流式输出，处理会话恢复、权限请求、选项选择、自动重启。
- **展示模式**：`/show` 细节模式（聚合推送）与 `/hide` 精简模式（只发开头与结尾），运行中可切换。
- **语音合成**：MiMo TTS 主引擎，Windows TTS、Edge-TTS 逐级降级；富文本（代码、表格）自动跳过朗读。

## 快速开始

### Windows 一键部署（推荐新手）

双击 `first_run.bat`。它会自动检查 Python、创建虚拟环境、安装依赖、运行配置向导（询问 LLM、检测 mimo 路径、平台凭证），最后启动。

之后日常启动只需双击 `start_mmc.bat`。

### 手动方式

```bash
# 1. 安装依赖（建议先建虚拟环境）
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 2. 配置环境变量
copy .env.example .env            # Windows；macOS/Linux 用 cp
# 编辑 .env，按需填入 API Key 与平台凭证

# 3. 运行
python main.py
```

前置条件：已安装 [MiMo Code CLI](https://github.com/XiaomiMiMo)（命令 `mimo` 可用，或在 `.env` 用 `MIMO_CODE_PATH` 指定路径）；Python ≥ 3.10。

## 目录结构

```
MIMO_Connect/
├── main.py                 # 异步事件循环入口
├── config.yaml             # 全局配置（LLM / TTS / CLI）
├── .env.example            # 环境变量模板
├── first_run.bat           # 首次一键部署（建 venv + 装依赖 + 向导 + 启动）
├── setup_and_run.bat       # 环境修复后启动（含依赖安装）
├── start_mmc.bat           # 日常快速启动
├── core/                   # 引擎编排、意图路由、段解析/重写、进度摘要、语音浓缩
│   ├── engine.py
│   ├── intent_router.py
│   ├── segment_parser.py
│   ├── segment_rewriter.py
│   ├── progress_summarizer.py
│   └── voice_condenser.py
├── agent/mimo_code.py      # MiMo Code CLI 适配器
├── platforms/              # feishu.py / weixin.py 平台适配器
├── voice/edge_tts.py       # TTS 提供商
├── scripts/                # 首次配置向导、记忆同步等工具脚本
├── tests/                  # pytest 测试
└── docs/                   # ADR、坑点记录、指南
```

## 配置说明

- **`.env`**：所有密钥与平台凭证（API Key、飞书 APP_ID/SECRET、微信 TOKEN/BOT_ID、mimo 路径、工作目录）。绝不提交到仓库。
- **`config.yaml`**：LLM 提供商与模型、TTS 引擎与降级顺序、CLI 选择、日志等非敏感配置。

## 中间层命令

在聊天窗口直接发送：`/show` 细节模式、`/hide` 精简模式、`/model` 查看当前模型、`/model <名称>` 切换模型、`/models` 列出可用模型、`/abort` 中断当前任务、`/help` 帮助。

## 测试

```bash
python -m pytest tests/ -q
```
