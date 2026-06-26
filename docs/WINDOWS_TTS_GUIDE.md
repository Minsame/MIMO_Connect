# Windows TTS 作为 MiMo TTS 降级方案

## 目录

1. [Windows TTS 实现方法](#1-windows-tts-实现方法)
2. [asyncio 集成](#2-asyncio-集成)
3. [语音参数配置](#3-语音参数配置)
4. [与 MiMo TTS 兼容性设计](#4-与-mimo-tts-兼容性设计)
5. [代码示例](#5-代码示例)

---

## 1. Windows TTS 实现方法

### 方案对比

| 方案 | 依赖 | 优点 | 缺点 |
|------|------|------|------|
| **win32com** | pywin32 | 性能最好，控制最精细 | 仅 Windows |
| **pyttsx3** | pyttsx3 | 跨平台，API 简单 | 性能一般 |
| **comtypes** | comtypes | 轻量级 | 需手动管理 COM |

### 安装依赖

`ash
# 方案1: win32com (推荐)
pip install pywin32

# 方案2: pyttsx3
pip install pyttsx3

# 方案3: comtypes
pip install comtypes
`

### 基础用法

`python
from core.windows_tts import create_windows_tts, WindowsTTSConfig

# 自动选择后端
config = WindowsTTSConfig(rate=0, volume=100)
tts = create_windows_tts(config, backend="auto")

# 同步播放
tts.speak("你好，世界！")

# 异步播放
tts.speak_async("这是异步播放")
`

---

## 2. asyncio 集成

### 异步封装

`python
import asyncio
from core.async_windows_tts import WindowsTTSFactory, TTSPriority

async def main():
    # 创建 TTS 实例
    tts = WindowsTTSFactory.create(
        voice_gender=TTSVoice性别.FEMALE,
        rate=0,
        volume=100,
    )
    
    # 启动 worker
    task = await tts.start()
    
    try:
        # 异步播放
        await tts.speak("你好，这是异步播放！")
        
        # 等待播放完成
        while tts.queue_size > 0:
            await asyncio.sleep(0.1)
            
    finally:
        await tts.stop()
        task.cancel()

# 运行
asyncio.run(main())
`

### 优先级调度

`python
# 高优先级消息 (审批/报错)
await tts.speak_critical("错误！文件不存在！")

# 普通优先级 (进度)
await tts.speak_normal("正在编译...")

# 低优先级 (闲聊)
await tts.speak_chat("今天天气不错")
`

### 打断机制

`python
# 打断当前播放，清空队列
await tts.interrupt()
`

---

## 3. 语音参数配置

### 语速控制

`python
from core.windows_tts import WindowsTTSConfig

config = WindowsTTSConfig(
    rate=-5,  # 慢速 (-10 到 +10)
    # rate=0,  # 正常
    # rate=5,  # 快速
)
`

### 音量控制

`python
config = WindowsTTSConfig(
    volume=80,  # 80% 音量 (0-100)
)
`

### 语音选择

`python
from core.windows_tts import WindowsTTSConfig, TTSVoice性别, create_windows_tts

# 按性别选择
config = WindowsTTSConfig(
    voice_gender=TTSVoice性别.FEMALE,  # 女声
)
tts = create_windows_tts(config)

# 获取可用语音列表
voices = tts.get_available_voices()
for voice in voices:
    print(f"{voice['name']}: {voice['language']}")
`

### 完整配置示例

`python
from core.async_windows_tts import (
    AsyncWindowsTTS,
    AsyncWindowsTTSConfig,
    WindowsTTSFactory,
)

config = AsyncWindowsTTSConfig(
    windows_tts_config=WindowsTTSConfig(
        voice_gender=TTSVoice性别.MALE,
        rate=2,           # 稍快
        volume=80,        # 80% 音量
        quality=TTSQuality.HIGH,
    ),
    backend="auto",           # 自动选择后端
    max_queue_size=50,        # 队列大小
    message_timeout=60.0,     # 消息超时
    enable_interrupt=True,    # 启用打断
)

tts = AsyncWindowsTTS(config)
`

---

## 4. 与 MiMo TTS 兼容性设计

### 统一接口

`python
from core.tts_engine import UnifiedTTS, UnifiedTTSConfig, create_tts

# 创建统一 TTS 引擎
config = UnifiedTTSConfig(
    # MiMo TTS 配置
    mimo_api_key="your-api-key",
    mimo_model="mimo-v2.5-tts",
    
    # Windows TTS 配置 (降级用)
    windows_voice_gender="female",
    windows_rate=0,
    windows_volume=100,
    
    # Edge TTS 配置 (在线降级)
    edge_voice="zh-CN-XiaoxiaoNeural",
    
    # 降级策略
    enable_fallback=True,
    fallback_order=[TTSBackend.MIMO, TTSBackend.WINDOWS, TTSBackend.EDGE],
)

tts = UnifiedTTS(config)
await tts.start()
`

### 降级策略

`python
# 自动降级流程:
# 1. MiMo TTS (主要)
#    ↓ 失败
# 2. Windows TTS (本地)
#    ↓ 失败
# 3. Edge TTS (在线)

# 检查当前后端
print(f"当前后端: {tts.current_backend}")

# 查看统计信息
print(f"统计: {tts.stats}")
`

### 与 ASR 联动

`python
# ASR 模块检测到用户说话时，调用 interrupt
async def on_user_speaking():
    await tts.interrupt()
    # 或者
    # await tts_engine.interrupt()
`

### 回调函数

`python
def on_speak_start(text):
    print(f"开始播放: {text[:20]}...")

def on_speak_end(text):
    print(f"播放完成: {text[:20]}...")

def on_error(error):
    print(f"播放错误: {error}")

tts.set_callbacks(
    on_start=on_speak_start,
    on_end=on_speak_end,
    on_error=on_error,
)
`

---

## 5. 代码示例

### 完整示例

`python
import asyncio
from core.tts_engine import UnifiedTTS, UnifiedTTSConfig, create_tts

async def main():
    # 创建 TTS 引擎
    tts, task = await create_tts(
        mimo_api_key="your-api-key",
        windows_backend="auto",
        enable_fallback=True,
    )
    
    try:
        # 播放消息
        await tts.speak("你好，欢迎使用 MIMO_Connect 语音助手！")
        
        # 等待播放完成
        while tts.is_speaking:
            await asyncio.sleep(0.1)
        
        # 查看统计
        print(f"统计: {tts.stats}")
        
    finally:
        await tts.stop()
        task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
`

### 运行示例

`ash
# 运行基础示例
python examples/windows_tts_example.py

# 运行完整 TTS 引擎
python -c "import asyncio; from core.tts_engine import main; asyncio.run(main())"
`

---

## 文件结构

`
Voice_Coding_MW/
├── core/
│   ├── __init__.py
│   ├── windows_tts.py           # Windows TTS 底层实现
│   ├── async_windows_tts.py     # 异步封装
│   └── tts_engine.py            # 统一 TTS 引擎
├── examples/
│   └── windows_tts_example.py   # 使用示例
├── requirements.txt             # 依赖
└── README.md                    # 本文档
`

---

## 注意事项

1. **依赖选择**: 推荐使用 pywin32 (win32com)，性能最好
2. **线程安全**: Windows TTS 使用 COM 对象，需要在主线程调用
3. **降级策略**: MiMo TTS 失败后会自动降级到 Windows TTS
4. **打断机制**: 用户说话时应调用 interrupt() 防止回声
5. **语音质量**: Windows TTS 质量一般，重要消息建议使用 MiMo TTS

---

## 常见问题

### Q: 如何安装 pywin32?

`ash
pip install pywin32
python Scripts/pywin32_postinstall.py -install
`

### Q: Windows TTS 声音太机械?

这是 Windows SAPI 的固有限制。建议:
- 优先使用 MiMo TTS
- 或使用 Edge TTS 作为在线降级

### Q: 如何在非 Windows 系统使用?

Windows TTS 仅支持 Windows。建议:
- 使用 edge-tts 作为跨平台降级方案
- 或使用 gTTS (Google TTS)
