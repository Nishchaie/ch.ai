# ch.ai System Architecture

ch.ai is an AI engineering team harness that orchestrates specialized agents with roles, feedback loops, and self-improvement.

## Layers

### Core

- **Harness**: Top-level runtime. Loads config, routes prompts, creates teams with dynamically selected roles.
- **ComplexityRouter**: Classifies prompt complexity (direct / small_team / full_pipeline) and determines which roles to spin up via `suggested_roles`.
- **Team**: Group of role-specialized agents. Coordinates task decomposition and execution. Receives a filtered roster from the Harness based on what the router suggested.
- **AgentRunner**: Wraps Provider + ToolRegistry for a role. Runs task execution loops.
- **TaskGraph**: DAG of TaskSpec with dependency tracking.
- **RoleRegistry**: Role definitions (Lead, Frontend, Backend, QA, etc.) with prompts and tool access.

### Orchestration

- **TeamCoordinator**: Receives TaskGraph, dispatches ready tasks to AgentRunners via ThreadPoolExecutor. Yields AgentEvent as tasks progress.
- **TaskScheduler**: Priority queue with dependency awareness. Per-role queues. Yields ready tasks.
- **ExecutionPlanManager**: Create, parse, update execution plans in `docs/exec-plans/`. Plans have YAML frontmatter + markdown body + machine-readable JSON task list.
- **FeedbackLoop**: Agent-to-agent review cycle. Produce → review → fix → repeat until approved.
- **MergeManager**: Git operations (create_branch, commit_changes, merge_branch) via gitpython.
- **WorktreeManager**: Per-task git worktrees in `.chai/worktrees/`. Create/remove worktrees.
- **ValidationGate**: Self-testing gate between task completion and review. Runs tests, golden principles, optional boot check. Creates fix tasks for failures.

### Knowledge

- **RepoKnowledge**: Scans repo structure. Identifies frontend/backend/test/doc files per role.
- **AgentsMdManager**: Generates and maintains AGENTS.md as table of contents (~100 lines).
- **DocsManager**: Manages `docs/` structure (design-docs, references, exec-plans).
- **DocGardener**: Scans for stale docs, broken cross-links, drift between docs and code.

### Quality

- **GoldenPrincipleChecker**: Parses `docs/golden-principles/index.md`. Runs regex, file_size, naming checks.
- **QualityScorer**: Grades frontend, backend, tests, docs. Saves to `docs/QUALITY_SCORE.md`.
- **AgentLinter**: Custom rules: file size, missing docstrings, with remediation instructions.
- **GarbageCollector**: Finds pattern drift, dead code, duplicated helpers. Produces cleanup TaskSpec list.

### Sessions

- **Database**: SQLite storage (aiosqlite). Tables: sessions, messages, team_runs.
- **HistoryManager**: Load/save conversation history per session.
- **maybe_compact**: Context compaction when near token limit. Summarizes middle, keeps head/tail.

### Providers & Tools

- **Provider**: ABC for model integrations (Claude Code CLI, Codex, Anthropic API, OpenAI).
- **ToolRegistry**: Tools with role-based access, parallel execution, file locking.
- **Tools**: read, write, edit, grep, shell, web_search, etc.

## Data Flow

1. User prompt → Harness → ComplexityRouter (classify + select roles) → Team (filtered roster)
2. Team Lead decomposes → TaskGraph
3. TeamCoordinator + TaskScheduler dispatch ready tasks
4. AgentRunners execute in worktrees (optional)
5. ValidationGate runs after each task
6. FeedbackLoop for review cycle
7. MergeManager merges branches
8. HistoryManager + Database persist; maybe_compact when needed

## Conventions

- Python: type hints, dataclasses, Pydantic models
- Tests: `tests/` mirrors `src/` structure
- Docs: `docs/design-docs/`, `docs/exec-plans/`, `docs/golden-principles/`
