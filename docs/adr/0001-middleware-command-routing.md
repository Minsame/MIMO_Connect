# ADR 0001: Middleware commands are handled before intent classification

## Status

Accepted

## Context

Users can ask for middleware-only actions such as `/show`, `/hide`, progress checks, or reading the previous reply aloud. These requests are about the middleware state, not tasks for MiMo Code.

If they are forwarded to MiMo Code, they can interrupt active work, create unrelated context, or cause the CLI to answer as if it were a coding task.

## Decision

The Engine handles middleware commands before LLM intent classification and before forwarding anything to the Agent.

This includes:

- `/show` detail mode
- `/hide` hidden mode
- progress/status queries while an Agent task is running
- voice replay requests for the previous reply

## Consequences

- Middleware behavior is deterministic and independent of LLM classification quality.
- User messages that are about middleware state do not pollute MiMo Code context.
- New middleware commands must be added to the Engine command layer, not to Agent prompts.
