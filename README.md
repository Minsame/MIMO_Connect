# MIMO_Connect

让你在飞书 / 微信里用聊天或语音直接驱动本地的 MiMo Code CLI 编程。MIMO_Connect 是一个中间层：它接收聊天平台的消息，做意图识别与格式整理，转发给 MiMo Code 执行，再把结果（含可选语音）回送到聊天窗口。

## 核心功能

- **多平台接入**：飞书（WebSocket 长连接）、微信（iLink Bot）。
- **意图路由**：基于 LLM 的意图分类（默认 DeepSeek，支持 OpenAI / Anthropic / SiliconFlow / DashScope），区分编程任务、闲聊、确认、中断等。
- **MiMo Code 桥接**：解析 `mimo run --format json` 的流式输出，处理会话恢复、权限请求、选项选择、自动重启。
- **展示模式**：`/show` 细节模式（聚合推送）与 `/hide` 精简模式（只发开头与结尾），运行中可切换。
- **语音合成**：MiMo TTS 主引擎，Windows TTS、Edge-TTS 逐级降级；富文本（代码、表格）自动跳过朗读。

## 环境要求

本项目提供两个相互独立的发行版，各自的环境要求如下。两者都依赖本机已安装 [MiMo Code CLI](https://github.com/XiaomiMiMo)（命令 `mimo` 可用，或在 `.env` 用 `MIMO_CODE_PATH` 指定路径），且运行时需要联网。

### GUI 版（Windows 桌面）

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11（64 位） |
| 运行 `MIMO_Connect.exe` | 无需额外环境，exe 自带 Python 运行时与全部依赖 |
| 从源码运行 | Python ≥ 3.10，`pip install -r requirements.txt`（含 PySide6） |
| 自行打包 | 在 Windows 上用 PyInstaller，依据 `MIMO_Connect.spec` |
| 必备外部依赖 | MiMo Code CLI、网络 |

### CLI 版（Linux 命令行）

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux x86_64（Ubuntu / Debian 等主流发行版） |
| 运行打包好的 `MIMO_Connect-cli` | 无需安装 Python，单文件自带运行时；目标机 glibc 版本需不低于打包机 |
| 从源码运行（`./mmc`） | Python ≥ 3.10，`pip install -r requirements.txt`（无需 PySide6） |
| 自行打包 | 必须在 Linux 上进行（PyInstaller 不能跨平台）：Python ≥ 3.10 + `python3-pip python3-venv python3-dev build-essential` |
| 必备外部依赖 | MiMo Code CLI、网络 |

> 说明：PyInstaller 不支持跨平台编译，Windows 上打不出 Linux 可执行，反之亦然。CLI 版的单文件可执行必须在 Linux（或 WSL）上打包。

## 快速开始

### Windows：桌面应用（推荐）

直接运行打包好的 `MIMO_Connect.exe`（单文件，约 85MB，自带 Python 与依赖，无需另装环境）。
首次启动会进入图形化引导向导（可在欢迎页选择中文 / 英文界面），依次配置中间层 LLM、聊天平台凭证、本地 mimo CLI 路径与工作目录。配置完成后程序常驻系统托盘：右键托盘图标可启停引擎、打开实时日志窗口、进入设置面板（含语言切换）。

配置文件 `.env` 与日志 `mimo_connect.log` 都保存在 exe 同目录。

> 从源码运行 GUI：`python gui_main.py`；或在已建 venv 时双击 `first_run.bat` 自动装依赖并引导。

### Linux：命令行（CLI 版）

方式 A — 打包成单文件可执行（拷一个文件即可运行，目标机无需 Python）：

```bash
# 1. 一次性装系统依赖（需要 sudo 密码）
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-dev build-essential

# 2. 一键打包（脚本会自建隔离 venv、装依赖、调用 PyInstaller）
bash build_linux_cli.sh

# 3. 运行（首次自动在同目录创建 .env / config.yaml / 日志并进入引导）
./dist/MIMO_Connect-cli
./dist/MIMO_Connect-cli --force-setup   # 强制重新配置
```

方式 B — 已有 Python，直接用启动器跑（更轻，无需打包）：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
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
├── MIMO_Connect.spec       # GUI 版打包配置（Windows，onefile + 精简 Qt）
├── MIMO_Connect-cli.spec   # CLI 版打包配置（Linux，无 Qt，体积更小）
├── build_linux_cli.sh      # Linux 一键打包 CLI 版的脚本
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
