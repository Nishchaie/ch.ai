/**
 * API client for ch.ai backend - matches Python types and endpoints.
 */

export type RoleType =
  | "lead"
  | "frontend"
  | "backend"
  | "prompt"
  | "researcher"
  | "qa"
  | "deployment"
  | "custom";

export type TaskStatus =
  | "pending"
  | "in_progress"
  | "reviewing"
  | "completed"
  | "failed"
  | "cancelled";

export interface Team {
  name: string;
  members: Record<string, { provider: string; model?: string }>;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  role: RoleType;
  dependencies?: string[];
  status: TaskStatus;
  acceptance_criteria?: string[];
  result?: string;
  error?: string;
}

export interface AgentEvent {
  type: string;
  data: unknown;
  role?: RoleType;
  task_id?: string;
}

export interface QualityScore {
  score: number;
  grade: string;
}

export interface ApiConfig {
  default_provider: string;
  default_model: string;
  theme: string;
  max_concurrent_agents: number;
}

export interface Plan {
  path: string;
  filename: string;
  title: string;
  task_count: number;
}

export interface PlanTask {
  id: string;
  title: string;
  description: string;
  role: string;
  status: string;
  dependencies: string[];
  acceptance_criteria: string[];
}

export interface PlanDetail {
  filename: string;
  title: string;
  description: string;
  tasks: PlanTask[];
}

export interface ActiveRun {
  run_id: string;
  prompt: string;
  source: string;
  status: string;
  started_at: number;
  event_count: number;
}

const BASE = "";

class ApiClient {
  async health(): Promise<{ status: string }> {
    const r = await fetch(`${BASE}/api/health`);
    return r.json();
  }

  async getTeams(): Promise<Team[]> {
    const r = await fetch(`${BASE}/api/teams`);
    return r.json();
  }

  async getTeamStatus(name: string): Promise<Record<string, unknown>> {
    const r = await fetch(`${BASE}/api/teams/${encodeURIComponent(name)}/status`);
    return r.json();
  }

  async startTeamRun(name: string, prompt: string): Promise<{ run_id: string; status: string; events: number }> {
    const r = await fetch(`${BASE}/api/teams/${encodeURIComponent(name)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async getTasks(): Promise<Task[]> {
    const r = await fetch(`${BASE}/api/tasks`);
    return r.json();
  }

  async getPlans(): Promise<Plan[]> {
    const r = await fetch(`${BASE}/api/plans`);
    return r.json();
  }

  async getPlanDetail(filename: string): Promise<PlanDetail> {
    const r = await fetch(`${BASE}/api/plans/${encodeURIComponent(filename)}`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async getQuality(): Promise<Record<string, QualityScore>> {
    const r = await fetch(`${BASE}/api/quality`);
    return r.json();
  }

  async getConfig(): Promise<ApiConfig> {
    const r = await fetch(`${BASE}/api/config`);
    return r.json();
  }

  async getProjectDir(): Promise<string> {
    const r = await fetch(`${BASE}/api/project-dir`);
    const data = await r.json();
    return data.project_dir;
  }

  /**
   * WebSocket connection for streaming agent events.
   * Returns a function to disconnect.
   */
  streamTeamEvents(
    teamName: string,
    prompt: string,
    onEvent: (event: AgentEvent) => void,
    onDone?: () => void,
    onError?: (err: string) => void,
    projectDir?: string
  ): () => void {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${proto}//${host}${BASE}/api/teams/${encodeURIComponent(teamName)}/stream`);
    const payload: Record<string, string> = { prompt };
    if (projectDir) payload.project_dir = projectDir;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      onDone?.();
    };
    ws.onopen = () => {
      ws.send(JSON.stringify(payload));
    };
    ws.onmessage = (e) => {
      const evt = JSON.parse(e.data) as AgentEvent;
      if (evt.type === "done") {
        finish();
      } else if (evt.type === "error") {
        if (!finished) {
          finished = true;
          onError?.(String(evt.data));
        }
      } else {
        onEvent(evt);
      }
    };
    ws.onerror = () => {
      if (!finished) {
        finished = true;
        onError?.("WebSocket error");
      }
    };
    ws.onclose = () => finish();
    return () => ws.close();
  }

  async getActiveRuns(): Promise<ActiveRun[]> {
    const r = await fetch(`${BASE}/api/runs/active`);
    return r.json();
  }

  /**
   * Subscribe to a CLI-initiated run's event stream.
   * Replays buffered events, then streams live.  Returns a disconnect fn.
   */
  subscribeToRun(
    runId: string,
    onEvent: (event: AgentEvent) => void,
    onDone?: () => void,
    onError?: (err: string) => void
  ): () => void {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(
      `${proto}//${host}${BASE}/api/runs/${encodeURIComponent(runId)}/stream`
    );
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      onDone?.();
    };
    ws.onmessage = (e) => {
      const evt = JSON.parse(e.data) as AgentEvent;
      if (evt.type === "done") {
        finish();
      } else if (evt.type === "error") {
        if (!finished) {
          finished = true;
          onError?.(String(evt.data));
        }
      } else {
        onEvent(evt);
      }
    };
    ws.onerror = () => {
      if (!finished) {
        finished = true;
        onError?.("WebSocket error");
      }
    };
    ws.onclose = () => finish();
    return () => ws.close();
  }
}

export const api = new ApiClient();
