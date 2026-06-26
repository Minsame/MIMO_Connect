# MIMO_Connect

让你在飞书 / 微信里用聊天或语音直接驱动本地的 MiMo Code CLI 编程。MIMO_Connect 是一个中间层：它接收聊天平台的消息，做意图识别与格式整理，转发给 MiMo Code 执行，再把结果（含可选语音）回送到聊天窗口。

## 核心功能

- **多平台接入**：飞书（WebSocket 长连接）、微信（iLink Bot）。
- **意图路由**：基于 LLM 的意图分类（默认 DeepSeek，支持 OpenAI / Anthropic / SiliconFlow / DashScope），区分编程任务、闲聊、确认、中断等。
- **MiMo Code 桥接**：解析 `mimo run --format json` 的流式输出，处理会话恢复、权限请求、选项选择、自动重启。
- **展示模式**：`/show` 细节模式（聚合推送）与 `/hide` 精简模式（只发开头与结尾），运行中可切换。
- **语音合成**：MiMo TTS 主引擎，Windows TTS、Edge-TTS 逐级降级；富文本（代码、表格）自动跳过朗读。

## 快速开始

### Windows：桌面应用（推荐）

直接运行打包好的 `MIMO_Connect.exe`（单文件，约 85MB，自带 Python 与依赖，无需另装环境）。
首次启动会进入图形化引导向导（可在欢迎页选择中文 / 英文界面），依次配置中间层 LLM、聊天平台凭证、本地 mimo CLI 路径与工作目录。配置完成后程序常驻系统托盘：右键托盘图标可启停引擎、打开实时日志窗口、进入设置面板（含语言切换）。

配置文件 `.env` 与日志 `mimo_connect.log` 都保存在 exe 同目录。

> 从源码运行 GUI：`python gui_main.py`；或在已建 venv 时双击 `first_run.bat` 自动装依赖并引导。

### Linux / macOS：命令行

```bash
./mmc                 # 首次未配置则进入分步引导，否则直接启动并持续打印日志
./mmc --force-setup   # 强制重新配置
```

命令行向导同样支持中文 / 英文（启动时选择，偏好写入 `.env` 的 `MIMO_CONNECT_LANG`，与 GUI 共用）。

### 手动方式（开发 / 调试）

```bash
# 1. 安装依赖（建议先建虚拟环境）
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 2. 启动
python gui_main.py                 # 图形界面（Windows）
python cli_main.py                 # 命令行（跨平台，未配置先引导）
```

前置条件：已安装 [MiMo Code CLI](https://github.com/XiaomiMiMo)（命令 `mimo` 可用，或在 `.env` 用 `MIMO_CODE_PATH` 指定路径）；从源码运行需 Python ≥ 3.10。`MIMO_Connect.exe` 自带运行时，但仍需本机已装 MiMo Code CLI 并联网。

### 自行打包 exe

```bash
pip install pyinstaller
pyinstaller MIMO_Connect.spec --noconfirm
# 产物：dist/MIMO_Connect.exe（onefile，已排除 WebEngine 等重型 Qt 模块）
```

## 目录结构

```
MIMO_Connect/
├── gui_main.py             # GUI 入口（桌面应用，打包进 exe）
├── cli_main.py             # CLI 入口（跨平台命令行）
├── main.py                 # 异步事件循环（引擎本体，被两个入口复用）
├── config.yaml             # 全局配置（LLM / TTS / CLI）
├── .env.example            # 环境变量模板
├── MIMO_Connect.spec       # PyInstaller 打包配置（onefile + 精简 Qt）
├── first_run.bat           # Windows 一键装依赖 + 引导（源码运行用）
├── mmc / mmc.bat           # 统一启动器（Linux 命令行 / Windows GUI）
├── gui/                    # 桌面 GUI：引导向导、托盘、设置、日志窗口、i18n
│   ├── app.py
│   ├── onboarding.py
│   ├── settings.py
│   ├── log_view.py
│   ├── tray.py
│   ├── theme.py
│   └── i18n.py             # 中文 / 英文界面文案
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
