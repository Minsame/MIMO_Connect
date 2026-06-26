# ADR 0002: Use working directory scope for MiMo Code authorization

## Status

Accepted

## Context

MiMo Code emits permission requests when asked to access paths outside its current working directory, for example:

```text
permission requested: external_directory (E:\Project_AI\*); auto-rejecting
```

One possible workaround is `--dangerously-skip-permissions`, but that grants broad permission and does not match the user's intended authorization model.

The user intent is: within an authorized project folder, MiMo Code can work without repeated prompts. It is not authorization to bypass all permission checks globally.

## Decision

Do not use `--dangerously-skip-permissions` for normal middleware authorization.

When a permission request targets a directory, prefer one of these safer approaches:

1. Start MiMo Code with its working directory set to the authorized project root.
2. If a running session requests access to a parent project directory, ask the user whether to switch the Agent working directory to that directory and retry the original instruction.
3. Keep permission request context visible to the user when asking for approval.

## Consequences

- Authorization remains scoped to a project directory.
- The Engine must parse stderr permission requests as well as stdout JSON events.
- Changing the Agent working directory may create a new MiMo session, so session continuity must be logged and tested.
