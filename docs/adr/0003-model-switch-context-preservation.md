# ADR 0003: Model switch does not intervene in MiMo Code memory or files

## Status

Accepted

## Context

MIMO_Connect is a middleware layer between chat platforms (Feishu/WeChat) and MiMo Code CLI. Its core principle is:

> **The middleware does NOT manage MiMo Code's conversation memory, session files, or session lifecycle.** MiMo Code handles its own memory format, session persistence, and context. The middleware only adapts, routes, and relays.

## Decision

When a user switches models via `/model <name>` or by selecting an option:

1. The middleware **only updates** its own Agent's `model` attribute via `set_model()`.
2. The middleware **does NOT** delete, modify, or clear any MiMo Code session files.
3. The middleware **does NOT** force-close existing MiMo CLI sessions.
4. The new model takes effect **naturally** when MiMo CLI starts the next new session (e.g. after the current task completes).

## Consequences

- MIMO_Connect stays faithful to its role: adapter, not memory manager.
- MiMo Code retains full ownership of its session files and conversation context.
- If MiMo CLI internally binds a model to a session and the model is no longer available, that is a MiMo Code-level issue. The middleware reports the error to the user but does not attempt to fix it by manipulating MiMo's files.
- Users receive a clear message: the model is set but takes effect on the next new session.
