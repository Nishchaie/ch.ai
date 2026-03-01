import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { api, type Task, type AgentEvent, type TaskStatus } from "../api/client";
import { useChatSessions } from "../store/chatSessions";
import { Circle, Clock, Loader2, CheckCircle2, XCircle, RotateCcw, Radio } from "lucide-react";

const COLUMNS: {
  status: Task["status"];
  title: string;
  icon: React.ReactNode;
  headerClass: string;
  dotClass: string;
}[] = [
  {
    status: "pending",
    title: "Pending",
    icon: <Clock size={13} />,
    headerClass: "text-gray-500",
    dotClass: "bg-gray-300",
  },
  {
    status: "in_progress",
    title: "In Progress",
    icon: <Loader2 size={13} className="animate-spin" />,
    headerClass: "text-blue-600",
    dotClass: "bg-blue-400",
  },
  {
    status: "reviewing",
    title: "Reviewing",
    icon: <RotateCcw size={13} />,
    headerClass: "text-amber-600",
    dotClass: "bg-amber-400",
  },
  {
    status: "completed",
    title: "Completed",
    icon: <CheckCircle2 size={13} />,
    headerClass: "text-emerald-600",
    dotClass: "bg-emerald-400",
  },
  {
    status: "failed",
    title: "Failed",
    icon: <XCircle size={13} />,
    headerClass: "text-red-500",
    dotClass: "bg-red-400",
  },
];

const ROLE_BADGE: Record<string, string> = {
  lead: "bg-amber-50 text-amber-700 border-amber-200",
  frontend: "bg-cyan-50 text-cyan-700 border-cyan-200",
  backend: "bg-green-50 text-green-700 border-green-200",
  prompt: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  researcher: "bg-blue-50 text-blue-700 border-blue-200",
  qa: "bg-red-50 text-red-700 border-red-200",
  deployment: "bg-yellow-50 text-yellow-700 border-yellow-200",
};

const DEFAULT_BADGE = "bg-gray-50 text-gray-600 border-gray-200";

function TaskCard({ task }: { task: Task }) {
  const badgeClass = ROLE_BADGE[task.role] ?? DEFAULT_BADGE;
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md hover:border-gray-300 transition-all cursor-default">
      <p className="text-sm font-medium text-gray-800 leading-snug">{task.title}</p>
      <div className="flex flex-wrap items-center gap-1.5 mt-2">
        <span
          className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full border font-medium ${badgeClass}`}
        >
          {task.role}
        </span>
      </div>
      {task.dependencies && task.dependencies.length > 0 && (
        <div className="text-xs text-gray-400 mt-2 flex items-center gap-1">
          <Circle size={8} className="flex-shrink-0" />
          <span className="truncate">Depends on {task.dependencies.length} task{task.dependencies.length !== 1 ? "s" : ""}</span>
        </div>
      )}
    </div>
  );
}

function mergeTasks(existing: Task[], incoming: Task[]): Task[] {
  const map = new Map(existing.map((t) => [t.id, t]));
  for (const t of incoming) {
    map.set(t.id, t);
  }
  return Array.from(map.values());
}

function applyEvent(tasks: Task[], evt: AgentEvent): Task[] {
  const data = evt.data as Record<string, unknown> | undefined;
  if (!data) return tasks;

  if (evt.type === "info" && Array.isArray(data.tasks)) {
    const newTasks: Task[] = (data.tasks as Record<string, unknown>[]).map((t) => ({
      id: String(t.id),
      title: String(t.title ?? t.id),
      role: (t.role as Task["role"]) ?? "backend",
      status: (t.status as TaskStatus) ?? "pending",
      dependencies: Array.isArray(t.dependencies) ? (t.dependencies as string[]) : [],
      description: t.description ? String(t.description) : undefined,
    }));
    return mergeTasks(tasks, newTasks);
  }

  if (evt.type === "status") {
    if (data.task_started) {
      const id = String(data.task_started);
      return tasks.map((t) => (t.id === id ? { ...t, status: "in_progress" as TaskStatus } : t));
    }
    if (data.task_completed) {
      const id = String(data.task_completed);
      return tasks.map((t) => (t.id === id ? { ...t, status: "completed" as TaskStatus } : t));
    }
  }

  if (evt.type === "error" && evt.task_id) {
    return tasks.map((t) => (t.id === evt.task_id ? { ...t, status: "failed" as TaskStatus } : t));
  }

  return tasks;
}

function deriveTasksFromEvents(events: AgentEvent[]): Task[] {
  let tasks: Task[] = [];
  for (const evt of events) {
    tasks = applyEvent(tasks, evt);
  }
  return tasks;
}

function TaskBoardView({ tasks, isLive, sessionTitle }: { tasks: Task[]; isLive: boolean; sessionTitle?: string }) {
  if (tasks.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Task Board</h2>
          <p className="text-gray-500 text-sm mt-1">
            {sessionTitle ? `Tasks for: ${sessionTitle}` : "Real-time task progress across agents"}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center shadow-sm">
          <p className="text-gray-500 text-sm">
            No active tasks. Run{" "}
            <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
              chai run "your prompt"
            </code>{" "}
            or use the Console to create tasks.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Task Board</h2>
          <p className="text-gray-500 text-sm mt-1">
            {sessionTitle && <span className="text-gray-400">{sessionTitle} · </span>}
            {tasks.length} task{tasks.length !== 1 ? "s" : ""} total
          </p>
        </div>
        {isLive && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full">
            <Radio size={10} className="animate-pulse" />
            Live
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {COLUMNS.map(({ status, title, icon, headerClass, dotClass }) => {
          const columnTasks = tasks.filter((t) => t.status === status);
          return (
            <div key={status} className="flex flex-col gap-2">
              <div className={`flex items-center gap-2 px-1 mb-1 ${headerClass}`}>
                {icon}
                <span className="text-xs font-semibold uppercase tracking-wide">{title}</span>
                <span className="ml-auto text-xs font-medium bg-gray-100 text-gray-500 px-1.5 rounded-full">
                  {columnTasks.length}
                </span>
              </div>

              <div className="space-y-2 min-h-[60px]">
                {columnTasks.map((t) => (
                  <TaskCard key={t.id} task={t} />
                ))}
                {columnTasks.length === 0 && (
                  <div className="rounded-lg border border-dashed border-gray-200 p-3 flex items-center justify-center">
                    <span className={`w-1.5 h-1.5 rounded-full ${dotClass} opacity-40`} />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function TaskBoard() {
  const { activeSessionId, getSession } = useChatSessions();

  const activeSession = activeSessionId ? getSession(activeSessionId) : undefined;
  const sessionTasks = useMemo(
    () => (activeSession ? deriveTasksFromEvents(activeSession.events) : null),
    [activeSession]
  );

  if (sessionTasks !== null) {
    return (
      <TaskBoardView
        tasks={sessionTasks}
        isLive={false}
        sessionTitle={activeSession?.title}
      />
    );
  }

  return <GlobalTaskBoard />;
}

function GlobalTaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLive, setIsLive] = useState(false);
  const subscribedRunRef = useRef<string | null>(null);
  const disconnectRef = useRef<(() => void) | null>(null);

  const handleEvent = useCallback((evt: AgentEvent) => {
    setTasks((prev) => applyEvent(prev, evt));
  }, []);

  useEffect(() => {
    api.getTasks().then((t) => setTasks((prev) => mergeTasks(prev, t))).catch(() => {});
    const interval = setInterval(() => {
      api.getTasks().then((t) => setTasks((prev) => mergeTasks(prev, t))).catch(() => {});
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const runs = await api.getActiveRuns();
        if (cancelled) return;
        const active = runs.find((r) => r.status === "running");
        if (active && active.run_id !== subscribedRunRef.current) {
          disconnectRef.current?.();
          subscribedRunRef.current = active.run_id;
          setIsLive(true);

          const disconnect = api.subscribeToRun(
            active.run_id,
            handleEvent,
            () => {
              setIsLive(false);
              subscribedRunRef.current = null;
              disconnectRef.current = null;
            },
            () => {
              setIsLive(false);
              subscribedRunRef.current = null;
              disconnectRef.current = null;
            },
          );
          disconnectRef.current = disconnect;
        } else if (!active && subscribedRunRef.current) {
          setIsLive(false);
          subscribedRunRef.current = null;
        }
      } catch {
        // API server may not be reachable
      }
    };

    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
      disconnectRef.current?.();
    };
  }, [handleEvent]);

  return <TaskBoardView tasks={tasks} isLive={isLive} />;
}
