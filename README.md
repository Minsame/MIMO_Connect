> # ⚠️ 安全提示
> **MiMo Code CLI 以 `--dangerously-skip-permissions` 模式启动（跳过所有权限确认），请确保运行环境可信。**

# MIMO_Connect

在飞书 / 微信里用聊天或语音直接驱动本地的 MiMo Code CLI 编程。

MIMO_Connect 是一个中间层：接收聊天平台消息 → LLM 意图识别与格式整理 → 转发 MiMo Code 执行 → 结果（含可选语音）回送聊天窗口。

## 功能

- **飞书 / 微信双平台**：飞书用 WebSocket 长连接，微信用 iLink Bot（扫码登录）。推荐飞书，支持更全面。
- **LLM 意图路由**：DeepSeek / OpenAI / Anthropic / SiliconFlow / DashScope，区分编程任务、闲聊、确认、中断。
- **MiMo Code 桥接**：解析 `mimo run --format json` 流式输出，处理会话恢复、权限请求、选项选择。
- **展示模式**：`/show` 细节模式（聚合推送）与 `/hide` 精简模式（只发开头与结尾）。
- **语音合成**：MiMo TTS 主引擎，Edge-TTS 降级备用；代码/表格自动跳过朗读。

## 前置条件

- **[MiMo Code CLI](https://github.com/XiaomiMiMo)**：本机已安装，命令 `mimo` 可用（或在 `.env` 中用 `MIMO_CODE_PATH` 指定路径）。
- **网络**：运行时需要联网（调用 LLM API、MiMo Code CLI）。
- **Python ≥ 3.10**：从源码运行需要；GUI exe 和 CLI 单文件版自带运行时。

## 快速开始

### Windows 桌面应用（推荐）

直接运行打包好的 `MIMO_Connect.exe`（约 85MB，自带 Python 与依赖）。首次启动进入图形化引导向导，依次配置中间层 LLM、聊天平台凭证、mimo CLI 路径与工作目录。配置后程序常驻系统托盘，右键可启停引擎、查看日志、进入设置。

配置文件 `.env` 与日志默认在 `%USERPROFILE%\.config\mimo_connect\`，可用环境变量 `MIMO_CONNECT_HOME` 覆盖。

> 从源码运行：`pip install -r requirements.txt` → `python gui_main.py`

### Linux 命令行

安装：

```bash
git clone https://github.com/Minsame/MIMO_Connect.git MIMO_Connect && cd MIMO_Connect
bash install.sh
# 国内网络加速：
# MMC_PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple bash install.sh
```

启动与常用命令：

```bash
mmc                  # 首次进入分步引导；之后启动引擎到后台
mmc status           # 查看运行状态（PID / 平台 / 模型）
mmc logs -f          # 实时跟随日志（从本次启动开始，Ctrl-C 退出）
mmc restart          # 重启引擎（重新读取配置）
mmc stop             # 停止引擎
mmc config           # 重新配置，完成后自动重启
mmc help             # 完整命令列表
```

`install.sh` 会把 `mmc` 软链到 `~/.local/bin/mmc`，若该目录在 PATH 中即可任意目录直接运行。配置与日志默认在 `~/.config/mimo_connect/`，可用 `MIMO_CONNECT_HOME` 覆盖。

> **微信用户**：选择微信平台后会弹出二维码，用手机微信扫码完成登录。Token 会自动保存到 `.env`，过期后重新运行 `mmc config` 扫码即可。

### 打包成单文件分发

**Windows exe**（需在 Windows 上打包）：

```bash
pip install pyinstaller
pyinstaller MIMO_Connect.spec --noconfirm
# 产物：dist/MIMO_Connect.exe
```

**Linux CLI 单文件**（需在 Linux/WSL 上打包）：

```bash
sudo apt-get install -y python3-pip python3-venv python3-dev build-essential
bash build_linux_cli.sh
# 产物：dist/MIMO_Connect-cli
```

> PyInstaller 不支持跨平台编译，Windows 上打不出 Linux 可执行，反之亦然。

## 聊天命令

在飞书/微信聊天窗口直接发送：

| 命令 | 说明 |
|------|------|
| `/show` | 细节模式，聚合推送过程 |
| `/hide` | 精简模式，只发开头与结尾 |
| `/model` | 查看当前模型 |
| `/model <名称>` | 切换模型（下次新对话生效） |
| `/models` | 列出可用模型 |
| `/abort` 或 `/stop` | 中断当前任务 |
| `/connect` | 查看接入提示 |
| `/help` | 帮助 |

## 配置

- **`.env`**：API Key、飞书 APP_ID/SECRET、微信 TOKEN/BOT_ID、mimo 路径、工作目录等敏感信息。
- **`config.yaml`**：LLM 提供商与模型、TTS 引擎与降级顺序、日志级别等非敏感配置。

## 目录结构

```
MIMO_Connect/
├── gui_main.py             # GUI 入口（Windows 桌面）
├── cli_main.py             # CLI 入口（跨平台命令行）
├── main.py                 # 异步引擎本体（被两个入口复用）
├── mmc / mmc.bat           # 统一启动器
├── install.sh              # Linux 一键安装
├── build_linux_cli.sh      # Linux CLI 打包脚本
├── MIMO_Connect.spec       # GUI 打包配置（Windows）
├── MIMO_Connect-cli.spec   # CLI 打包配置（Linux）
├── core/                   # 引擎、意图路由、段解析/重写、进度摘要
├── agent/mimo_code.py      # MiMo Code CLI 适配器
├── platforms/              # feishu.py / weixin.py 平台适配器
├── voice/edge_tts.py       # TTS 提供商（MiMo TTS / Edge-TTS / Windows TTS）
├── gui/                    # 桌面 GUI（引导、托盘、设置、日志、i18n）
├── scripts/                # 首次配置向导等工具脚本
└── tests/                  # pytest 测试
```
