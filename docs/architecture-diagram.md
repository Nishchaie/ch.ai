# ch.ai Architecture Diagrams

Standalone Mermaid diagrams for ch.ai system architecture.

## 1. System Overview Flowchart

```mermaid
flowchart TB
    User([User])
    CLI[CLI]
    Harness[Harness]
    Team[Team]
    Lead[Team Lead]
    TaskGraph[TaskGraph]
    Roles[Roles]
    Agents[Agents]
    Providers[Providers]
    Tools[Tools]

    User --> CLI
    CLI --> Harness
    Harness --> Team
    Team --> Lead
    Lead --> TaskGraph
    TaskGraph --> Roles
    Roles --> Agents
    Agents --> Providers
    Agents --> Tools
```

## 2. Provider Architecture

```mermaid
flowchart LR
    subgraph CLI["CLI-Wrapped Mode"]
        CC[Claude Code CLI]
        CX[Codex CLI]
    end

    subgraph API["Direct API Mode"]
        AN[Anthropic API]
        OAI[OpenAI API]
        CUS[Custom BYOM]
    end

    Harness[Harness]
    Tools[Tools]

    Harness --> CC
    Harness --> CX
    Harness --> AN
    Harness --> OAI
    Harness --> CUS
    AN --> Tools
    OAI --> Tools
    CUS --> Tools
    CC -.-> |manages own| Tools
    CX -.-> |manages own| Tools
```

## 3. Self-Improvement Loop

```mermaid
flowchart TD
    Execute[Execute]
    Validate[Validate]
    Fix[Fix]
    Learn[Learn]

    Execute --> Validate
    Validate -->|Pass| Learn
    Validate -->|Fail| Fix
    Fix --> Execute
    Learn --> Execute
```

## Rendering to SVG

Use Mermaid CLI to export diagrams:

```bash
mmdc -i docs/architecture-diagram.md -o docs/architecture.svg -t dark
```

Requires: `npm install -g @mermaid-js/mermaid-cli`
