# Vibe Voice Middleware 项目生成指令

## 项目概述
构建一个轻量级语音交互中间层，作为本地已配置的 Coding CLI（MiMo Code）的上层控制器。通过微信（iLink Bot API）接收语音消息（iLink云端自动转录），由 LLM（默认DeepSeek，支持多提供商切换）进行意图解析与状态路由，驱动 CLI 执行 Plan/Build 流程，并将 CLI 反馈通过 TTS（Edge TTS/OpenAI TTS）语音回复用户，实现全语音闭环编程。核心原则：复用Hermes Agent的微信对接和TTS能力，专注LLM意图解析→CLI控制→语音回复的闭环。

## 技术架构
- **微信对接**：复用Hermes Agent的iLink Bot API（weixin.py）
- **语音输入**：iLink云端自动转录，无需本地ASR
- **意图解析**：DeepSeek LLM，支持多提供商切换
- **TTS引擎**：Edge TTS（默认免费）/ OpenAI TTS / 自定义命令
- **CLI控制**：MiMo Code

## 目录结构
```
vvm/
├── config.yaml              # 全局配置
├── .env.example             # 环境变量模板
├── main.py                  # 异步事件循环入口
├── gateway/
│   └── weixin.py            # 微信iLink对接（from Hermes Agent）
├── core/
│   ├── llm_router.py        # LLM 多提供商路由器
│   ├── state_machine.py     # 纯逻辑状态机
│   └── cli_optimizer.py     # CLI 输出优化器
├── tts/
│   └── tts_tool.py          # TTS工具（Edge TTS/OpenAI TTS）
└── prompts/
    ├── user_intent.txt      # 意图分类提示词
    ├── cli_state.txt        # 状态分类提示词
    ├── cli_optimization.txt # 输出优化提示词
    └── error_conversion.txt # 错误转换提示词
```

## 数据流

```
用户微信语音消息
    ↓ (iLink云端自动转录)
weixin.py 接收文本消息
    ↓
llm_router.parse_user_intent(text, current_state)
    ↓
state_machine.transition(new_state)
    ↓
CLI执行任务（MiMo Code）
    ↓
cli_optimizer.optimize_output(cli_output)
    ↓
tts_tool.text_to_speech(optimized_text)
    ↓
weixin.py 发送语音/文本回复
```

## 核心模块实现规范

### 1. LLM 路由器 (core/llm_router.py)
- **LLM选型**：默认使用DeepSeek，支持多提供商动态切换（OpenAI、Anthropic、SiliconFlow、DashScope）
- **配置管理**：使用Pydantic BaseSettings管理配置，API Key通过.env文件管理
- **核心方法**：
  - parse_user_intent(user_text, current_state)：返回严格 JSON {"action": "APPROVE|REJECT|MODIFY_PLAN|CHAT|INTERRUPT", "payload": "..."}。
  - classify_cli_output(output_chunk)：返回状态枚举 PLANNING|BUILDING|WAITING_APPROVAL|ERROR|COMPLETED|NONE。
- **技术要求**：必须使用 temperature=0 和 response_format={"type": "json_object"} 保证输出确定性
- **多提供商支持**：通过LangChain的init_chat_model统一接口，支持运行时切换提供商

### 2. 纯逻辑状态机 (core/state_machine.py)
- 仅维护状态流转表，不包含任何 NLP 逻辑。
- 合法流转：IDLE→PLANNING→WAITING_APPROVAL→BUILDING→COMPLETED；WAITING_APPROVAL 可回退 PLANNING；BUILDING 可转 ERROR/WAITING_APPROVAL。
- transition(new_state) 方法校验合法性后更新状态，非法流转记录警告但不崩溃。

### 3. MiMo TTS 异步引擎 (core/tts_engine.py)
- **主引擎**：使用mimo-v2.5-tts，支持声音克隆和自定义设计
- **降级方案**：MiMo不可用时自动降级到Windows自带TTS，再降级到Edge-TTS
- **模型选择**：
  - mimo-v2.5-tts：通用语音合成，适合大多数场景
  - mimo-v2.5-tts-voiceclone：声音克隆，需要声音样本
  - mimo-v2.5-tts-voicedesign：自定义声音设计
  - mimo-v2-tts：基础版本，性能较弱
- **优先级调度**：使用asyncio.PriorityQueue，审批/报错消息优先级=1，普通进度=5，闲聊=9
- **打断机制**：支持用户说话时自动停止，防止回声死循环

### 4. CLI 伪终端桥接 (cli_bridge/pty_wrapper.py)
- 使用 pty.openpty() 创建伪终端，解决非交互式 CLI 输出格式异常问题。
- _read_loop 中必须用正则 \x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]) 清洗 ANSI 转义序列后再送入 LLM。
- write(text) 方法向 master fd 写入换行结尾的 UTF-8 字节。

### 5. ASR 引擎 (core/asr_engine.py)
- TTS is_speaking=True 时软件层丢弃音频帧，防止回声死循环。
- 支持 VAD 检测用户开口即触发 tts.interrupt()。
- ASR 结果直接透传给 llm_router.parse_user_intent，不做任何预处理。

## 配置文件设计

### config.yaml（主配置文件）
支持灵活的配置管理，包括：
- LLM多提供商配置（DeepSeek、OpenAI、Anthropic等）
- TTS引擎配置（MiMo、Windows、Edge-TTS）
- ASR引擎配置（Whisper、Azure、Google）
- CLI工具配置（MiMo Code、Hermes）
- 状态机配置
- 日志配置
- 提示词配置

### .env.example（环境变量模板）
管理敏感信息，包括：
- 各LLM提供商的API Key
- MiMo TTS API Key
- ASR服务配置
- CLI工具路径

### 配置加载器
使用ConfigLoader类统一管理配置，支持：
- 点分路径获取配置值
- 环境变量自动加载
- 默认值设置

## 中间件提示词设计

### 目的
设计提示词帮助CLI生成便于语音播报的内容，提升用户体验。

### 提示词类型
1. **CLI输出优化提示词**：将技术输出转换为用户友好的语音播报
2. **错误信息转换提示词**：将错误信息转换为易懂的语音提示
3. **进度报告生成提示词**：将进度信息转换为简洁的语音播报
4. **审批请求转换提示词**：将审批请求转换为清晰的语音提示

### 实现方案
- 使用LLM进行文本转换
- 支持不同场景的提示词模板
- 集成到TTS引擎中自动调用

## 多轮对话管理

### 对话历史维护
- 保留最近5-10轮对话上下文
- 使用滑动窗口管理历史
- 重要决策持久化存储

### 上下文窗口管理
- 当对话过长时，保留关键信息（当前状态、用户意图）
- 使用摘要技术压缩历史
- 支持话题切换和恢复

### 记忆机制
- 重要偏好和决策持久化
- 支持用户自定义记忆
- 隐私保护机制

## 错误处理与恢复

### LLM识别失败
- 最多重试3次，每次间隔递增
- 失败后使用默认处理（CHAT）
- 记录错误日志供分析

### 状态机异常
- 非法状态流转记录警告但不崩溃
- 提供状态恢复机制
- 支持手动重置状态

### 网络中断
- 缓存关键操作
- 网络恢复后自动重试
- 提供离线模式支持

### CLI无响应
- 设置超时机制（30秒）
- 超时后强制重启CLI
- 提供状态恢复方案

## 关键约束
1. LLM 选型：依据用户指定的API
2. 无状态路由：LLM Router 不维护对话历史，仅依赖「当前状态 + 最新输入」做决策，历史由底层 CLI 自行管理。
3. Prompt 缓存：两个分类 Prompt 必须启用 API Prompt Caching。
4. ANSI 清洗前置：PTY 原始数据必须先清洗再送 LLM，避免 Token 浪费与状态误判。
5. TTS 降级：MiMo 不可用时自动切换本地/Edge-TTS，保证审批流不阻塞。

## 测试策略

### 单元测试
- 覆盖核心模块（LLM路由、状态机、TTS）
- 使用mock测试外部依赖
- 测试覆盖率目标 > 80%

### 集成测试
- 模拟完整语音交互流程
- 测试端到端功能
- 测试异常场景处理

### 性能测试
- 响应延迟 < 2秒
- 内存占用 < 500MB
- 并发处理能力测试

### 兼容性测试
- Windows/Linux/macOS三平台验证
- 不同Python版本兼容性
- 不同LLM提供商兼容性

## MVP 验证顺序
1. 跑通 PTY + ANSI 清洗，稳定读取 CLI 干净文本。
2. 接入本地小模型调优分类 Prompt，意图准确率 > 95%，状态准确率 > 90%。
3. 接入 MiMo TTS + VAD 联动，消除回声死循环。
4. 串联 StateMachine，完成「语音提需求 → AI 出计划 → 语音审批 → 自动 Build → 语音汇报」端到端闭环。