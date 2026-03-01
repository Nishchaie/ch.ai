# Core Beliefs

Agent-first development principles that guide ch.ai's design.

- **Agents need structure**: Unstructured prompts lead to thrashing. Task graphs with clear dependencies and acceptance criteria give agents a map to follow.
- **Self-testing gates prevent drift**: Running tests and lint between execution and review catches regressions before they compound.
- **Golden principles enforce standards mechanically**: Code standards in `docs/golden-principles/` are checked automatically—agents get actionable feedback, not vague "write better code" instructions.
- **Context compaction extends runway**: Long conversations hit model limits. Summarizing the middle while preserving head and tail lets agents stay productive without losing critical context.
