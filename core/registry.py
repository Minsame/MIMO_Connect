"""Plugin registry for MIMO_Connect.

Agents and platforms register themselves via register_* functions.
Inspired by CC-Connect's init() registration pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .interfaces import Agent, Platform, VoiceProvider

_agents: dict[str, type[Agent]] = {}
_platforms: dict[str, type[Platform]] = {}
_voice_providers: dict[str, type[VoiceProvider]] = {}


def register_agent(name: str, cls: type[Agent]) -> None:
    _agents[name] = cls


def register_platform(name: str, cls: type[Platform]) -> None:
    _platforms[name] = cls


def register_voice_provider(name: str, cls: type[VoiceProvider]) -> None:
    _voice_providers[name] = cls


def get_agent(name: str) -> type[Any] | None:
    return _agents.get(name)


def get_platform(name: str) -> type[Any] | None:
    return _platforms.get(name)


def get_voice_provider(name: str) -> type[Any] | None:
    return _voice_providers.get(name)


def list_agents() -> list[str]:
    return list(_agents.keys())


def list_platforms() -> list[str]:
    return list(_platforms.keys())


def list_voice_providers() -> list[str]:
    return list(_voice_providers.keys())
