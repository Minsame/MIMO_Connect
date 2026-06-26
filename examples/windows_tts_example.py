# -*- coding: utf-8 -*-
"""
Windows TTS 使用示例

展示如何在 MIMO_Connect 项目中使用 Windows TTS
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.windows_tts import (
    WindowsTTSConfig,
    TTSVoice性别,
    TTSQuality,
    create_windows_tts,
)
from core.async_windows_tts import (
    AsyncWindowsTTS,
    AsyncWindowsTTSConfig,
    WindowsTTSFactory,
    TTSPriority,
)


async def example_basic():
    """基础用法示例"""
    print("=" * 60)
    print("示例 1: 基础用法")
    print("=" * 60)
    
    # 创建 TTS 实例 (自动选择后端)
    tts = WindowsTTSFactory.create(
        voice_gender=TTSVoice性别.FEMALE,
        rate=0,
        volume=100,
    )
    
    # 启动 worker
    task = await tts.start()
    
    try:
        # 播放文本
        await tts.speak("你好，我是 Windows 语音助手。")
        await asyncio.sleep(1)
        
        await tts.speak("正在为您处理请求...")
        await asyncio.sleep(1)
        
        # 等待队列处理完成
        while tts.queue_size > 0:
            await asyncio.sleep(0.1)
        
    finally:
        await tts.stop()
        task.cancel()


async def example_priority():
    """优先级示例"""
    print("=" * 60)
    print("示例 2: 优先级调度")
    print("=" * 60)
    
    tts = WindowsTTSFactory.create()
    task = await tts.start()
    
    try:
        # 模拟多条消息，高优先级消息会先播放
        await tts.speak_chat("这是闲聊消息，优先级最低。")
        await tts.speak_normal("这是普通进度消息。")
        await tts.speak_critical("错误！这是报错消息，优先级最高！")
        await tts.speak_normal("这是另一条普通消息。")
        
        # 等待播放完成
        while tts.queue_size > 0:
            await asyncio.sleep(0.1)
        
    finally:
        await tts.stop()
        task.cancel()


async def example_interrupt():
    """打断机制示例"""
    print("=" * 60)
    print("示例 3: 打断机制")
    print("=" * 60)
    
    tts = WindowsTTSFactory.create()
    task = await tts.start()
    
    try:
        # 播放长文本
        await tts.speak("这是一段很长的文本，需要几秒钟才能播放完成。")
        await tts.speak("这是第二条消息。")
        await tts.speak("这是第三条消息。")
        
        # 模拟用户打断
        await asyncio.sleep(1)
        print("用户打断！")
        await tts.interrupt()
        
        # 播放新消息
        await tts.speak("好的，我已停止。")
        
    finally:
        await tts.stop()
        task.cancel()


async def example_callback():
    """回调函数示例"""
    print("=" * 60)
    print("示例 4: 回调函数")
    print("=" * 60)
    
    tts = WindowsTTSFactory.create()
    
    # 设置回调
    def on_start(text):
        print(f"[开始播放] {text[:20]}...")
    
    def on_end(text):
        print(f"[播放完成] {text[:20]}...")
    
    tts.set_callbacks(on_start=on_start, on_end=on_end)
    
    task = await tts.start()
    
    try:
        await tts.speak("这是带有回调的播放。")
        await asyncio.sleep(2)
        
    finally:
        await tts.stop()
        task.cancel()


async def example_config():
    """配置示例"""
    print("=" * 60)
    print("示例 5: 各种配置")
    print("=" * 60)
    
    # 创建自定义配置
    config = AsyncWindowsTTSConfig(
        windows_tts_config=WindowsTTSConfig(
            voice_gender=TTSVoice性别.MALE,
            rate=2,           # 稍快
            volume=80,        # 80% 音量
            quality=TTSQuality.HIGH,
        ),
        backend="auto",
        max_queue_size=50,
        message_timeout=60.0,
        enable_interrupt=True,
    )
    
    tts = AsyncWindowsTTS(config)
    task = await tts.start()
    
    try:
        await tts.speak("这是自定义配置的播放。语速较快，音量80%。")
        await asyncio.sleep(2)
        
    finally:
        await tts.stop()
        task.cancel()


async def example_voice_list():
    """获取可用语音列表"""
    print("=" * 60)
    print("示例 6: 可用语音列表")
    print("=" * 60)
    
    tts = WindowsTTSFactory.create()
    voices = tts.get_available_voices()
    
    print(f"找到 {len(voices)} 个可用语音:")
    for i, voice in enumerate(voices, 1):
        print(f"  {i}. {voice['name']}")
        if 'language' in voice:
            print(f"     语言: {voice['language']}")
    
    # 选择特定语音
    if voices:
        print(f"\n使用第一个语音: {voices[0]['name']}")
        tts.select_voice(voices[0]['name'])


async def main():
    """运行所有示例"""
    print("Windows TTS 使用示例")
    print("=" * 60)
    
    # 运行示例
    await example_basic()
    print()
    await example_priority()
    print()
    await example_interrupt()
    print()
    await example_config()
    print()
    await example_voice_list()


if __name__ == "__main__":
    asyncio.run(main())
