# MIMO_Connect Gotchas

## stderr 非权限错误被静默丢弃

`_read_stderr` 原本只处理 `permission requested:` 模式的 stderr。模型错误、Bun 运行时错误等非权限 stderr 被只打日志就丢弃，导致用户看到"Agent 无响应"而不是真实错误。

**修复**：非权限 stderr 现在会生成 `EventType.ERROR` 事件，用户能看到具体报错。

## error 事件格式兼容性

MiMo CLI 的 `type: error` 事件中，`error` 字段可能是字符串或 dict。原始代码假设永远是 dict，会导致 AttributeError。

**修复**：`_handle_cli_error` 现在对 str/dict/other 三种类型都做了 fallback。

## 中间层不干预 MiMo Code 文件

中间层**绝不**删除、修改或清理 MiMo Code 的 session 持久化文件（`.mimocode/` 或 MiMo 的其他存储）。MiMo Code 自行管理其 session 生命周期和记忆格式。中间层只在转发时做适配和过滤。
