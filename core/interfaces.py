"""Core interfaces for MIMO_Connect.

Defines the contracts between platform, agent, voice, and engine layers.
Inspired by CC-Connect's interface-driven architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional


# ─── Message Types ───────────────────────────────────────────────────────────

class MessageType(Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    FILE = "file"


@dataclass
class Message:
    """Unified message type flowing through the system."""
    id: str
    content: str
    msg_type: MessageType = MessageType.TEXT
    from_user: str = ""
    to_user: str = ""
    context_token: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Reply:
    """Reply to send back through the platform."""
    content: str
    voice_path: Optional[str] = None
    msg_type: MessageType = MessageType.TEXT
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Event Types ─────────────────────────────────────────────────────────────

class EventType(Enum):
    TEXT_CHUNK = "text_chunk"
    DONE = "done"
    ERROR = "error"
    PERMISSION_REQUEST = "permission_request"
    STATUS = "status"


@dataclass
class Event:
    """Event emitted by an agent session."""
    type: EventType
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ─── Platform Interface ─────────────────────────────────────────────────────

class Platform(ABC):
    """Platform adapter interface.

    Each platform (WeChat, Telegram, etc.) implements this interface.
    The engine calls start() to begin receiving messages, and
    send_reply() to send responses back.
    """

    @abstractmethod
    def name(self) -> str:
        """Platform name for logging/config."""

    @abstractmethod
    async def start(self, handler: Callable[[Message], Any]) -> None:
        """Start receiving messages. Calls handler for each message."""

    @abstractmethod
    async def send_reply(self, reply: Reply, context_token: str = "") -> bool:
        """Send a reply back to the platform."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the platform adapter."""


# ─── Agent Interface ─────────────────────────────────────────────────────────

class AgentSession(ABC):
    """An active conversation session with an AI agent."""

    @abstractmethod
    async def send(self, prompt: str) -> None:
        """Send a prompt to the agent."""

    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        """Stream events from the agent."""

    @abstractmethod
    def alive(self) -> bool:
        """Check if the session is still active."""

    @abstractmethod
    async def close(self) -> None:
        """Close the session."""

    async def abort(self) -> None:
        """Abort current task but preserve session for resume. Default: same as close."""
        await self.close()


class Agent(ABC):
    """Agent adapter interface.

    Each AI agent (MiMo Code, Claude Code, etc.) implements this interface.
    The engine calls start_session() to create a new conversation.
    """

    @abstractmethod
    def name(self) -> str:
        """Agent name for logging/config."""

    @abstractmethod
    async def start_session(self, session_id: str, work_dir: str = "") -> AgentSession:
        """Start a new agent session."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the agent adapter."""

    async def list_models(self) -> list[str]:
        """Return available model names. Empty list if unsupported/unavailable."""
        return []


# ─── Voice Interface ─────────────────────────────────────────────────────────

class VoiceProvider(ABC):
    """Voice provider interface for TTS."""

    @abstractmethod
    def name(self) -> str:
        """Provider name."""

    @abstractmethod
    async def synthesize(self, text: str, output_path: str) -> Optional[str]:
        """Generate speech audio. Returns path to generated file."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available."""


# ─── Intent Router Interface ─────────────────────────────────────────────────

class IntentType(Enum):
    CHAT = "chat"
    CODE_TASK = "code_task"
    APPROVE = "approve"
    REJECT = "reject"
    INTERRUPT = "interrupt"
    MODIFY = "modify"
    VOICE_ON = "voice_on"
    VOICE_OFF = "voice_off"
    VOICE_LAST = "voice_last"
    SELECT_OPTION = "select_option"


@dataclass
class Intent:
    """Parsed user intent."""
    type: IntentType
    payload: str = ""
    confidence: float = 1.0
    option_index: int = -1


class IntentRouter(ABC):
    """Intent classification interface."""

    @abstractmethod
    async def classify(self, text: str, context: str = "", pending_options: Optional[list[dict]] = None) -> Intent:
        """Classify user intent from text."""
