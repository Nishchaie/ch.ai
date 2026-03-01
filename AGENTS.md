# ch.ai Agent Guide

> This file is a map, not an encyclopedia. It points you to where to look.

## Project Overview

ch.ai is an AI engineering team harness that orchestrates specialized agents with roles
(Team Lead, Frontend, Backend, Prompt, Researcher, QA, Deployment). Built in Python with
a TypeScript web frontend.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

## Directory Map

- `src/chai/core/` -- Team engine: harness, team, roles, agents, tasks, context
- `src/chai/providers/` -- Model providers: Claude Code CLI, Codex CLI, Anthropic API, OpenAI API, BYOM
- `src/chai/tools/` -- Agent tools: filesystem, grep, shell, browser, review, search
- `src/chai/orchestration/` -- Coordination: scheduling, planning, feedback loops, merge, worktrees, validation
- `src/chai/knowledge/` -- Repository knowledge: scanning, AGENTS.md management, doc gardening
- `src/chai/quality/` -- Enforcement: golden principles, quality scoring, linting, garbage collection
- `src/chai/sessions/` -- Persistence: SQLite sessions, history, context compaction
- `src/chai/ui/` -- Terminal UI: rich output, dashboard, themes
- `src/chai/cli.py` -- CLI entry point (click)
- `src/chai/api.py` -- FastAPI server for web frontend
- `frontend/` -- React/TypeScript web dashboard

## Key Concepts

- **Harness**: The runtime that boots teams and manages agent lifecycles
- **Team**: A group of role-specialized agents coordinated by a Team Lead
- **Role**: Defines allowed tools, autonomy level, context scope, system prompt
- **TaskGraph**: DAG of tasks with dependencies, topologically sorted for parallel dispatch
- **ValidationGate**: Automated test/lint/boot validation between execution and review
- **Golden Principles**: Mechanically enforced code standards in `docs/golden-principles/`
- **Execution Plans**: First-class plan artifacts in `docs/exec-plans/`

## Conventions

- Python code uses type hints, dataclasses, and Pydantic models
- Provider interface in `providers/base.py` is the contract all providers implement
- Tool interface in `tools/base.py` is the contract all tools implement
- Shared types live in `types.py` -- do not duplicate type definitions
- Tests mirror source structure under `tests/`

## Documentation

- `docs/design-docs/` -- Design decisions and core beliefs
- `docs/exec-plans/` -- Active and completed execution plans
- `docs/golden-principles/` -- Mechanical code standards
- `docs/references/` -- External reference material
- `docs/QUALITY_SCORE.md` -- Quality grades per domain
