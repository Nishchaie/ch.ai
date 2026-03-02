import { useState, useRef, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowUp, ChevronDown, ChevronRight, Sparkles, Terminal, Wrench, CheckCircle, XCircle, AlertCircle, Zap, FolderOpen } from "lucide-react";
import { api, type AgentEvent, type ActiveRun } from "../api/client";
import { useChatSessions, deriveTitle } from "../store/chatSessions";
import DirectoryPicker from "./DirectoryPicker";

const ROLE_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  lead: { bg: "bg-amber-100", text: "text-amber-700", dot: "bg-amber-500" },
  frontend: { bg: "bg-cyan-100", text: "text-cyan-700", dot: "bg-cyan-500" },
  backend: { bg: "bg-green-100", text: "text-green-700", dot: "bg-green-500" },
  prompt: { bg: "bg-fuchsia-100", text: "text-fuchsia-700", dot: "bg-fuchsia-500" },
  researcher: { bg: "bg-blue-100", text: "text-blue-700", dot: "bg-blue-500" },
  qa: { bg: "bg-red-100", text: "text-red-700", dot: "bg-red-500" },
  deployment: { bg: "bg-yellow-100", text: "text-yellow-700", dot: "bg-yellow-500" },
  system: { bg: "bg-gray-100", text: "text-gray-600", dot: "bg-gray-400" },
};

const ROLE_INITIAL: Record<string, string> = {
  lead: "L", frontend: "FE", backend: "BE", prompt: "P",
  researcher: "R", qa: "QA", deployment: "D", system: "S",
};

type MessageType =
  | { kind: "user"; text: string }
  | { kind: "text"; role: string; text: string }
  | { kind: "tool_call"; role: string; name: string; args: unknown }
  | { kind: "tool_result"; role: string; success: boolean; output: string }
  | { kind: "status"; role: string; text: string }
  | { kind: "error"; text: string };

function buildMessages(events: AgentEvent[]): MessageType[] {
  const messages: MessageType[] = [];
  for (const evt of events) {
    const role = evt.role ?? "system";
    const data = evt.data as Record<string, unknown> | undefined;

    if (evt.type === "text") {
      messages.push({ kind: "text", role, text: String(evt.data) });
    } else if (evt.type === "tool_call") {
      messages.push({
        kind: "tool_call",
        role,
        name: (data?.name as string) ?? "?",
        args: data?.args,
      });
    } else if (evt.type === "tool_result") {
      messages.push({
        kind: "tool_result",
        role,
        success: Boolean(data?.success),
        output: String(data?.output ?? ""),
      });
    } else if (evt.type === "status") {
      if (data?.phase) {
        messages.push({ kind: "status", role, text: `Phase: ${data.phase}` });
      } else if (data?.task_started) {
        const title = (data.title as string) ?? String(data.task_started);
        messages.push({ kind: "status", role, text: `Started: ${title}` });
      } else if (data?.task_completed) {
        messages.push({ kind: "status", role, text: "Task completed" });
      }
    } else if (evt.type === "activity") {
      const msg = (data as { message?: string })?.message;
      if (msg) {
        messages.push({ kind: "status", role, text: msg });
      }
    } else if (evt.type === "error") {
      messages.push({ kind: "error", text: String(evt.data) });
    } else if (evt.type === "info" && data && Array.isArray(data.tasks)) {
      messages.push({
        kind: "status",
        role: "system",
        text: `Created ${(data.tasks as unknown[]).length} tasks`,
      });
    }
  }
  return messages;
}

function RoleAvatar({ role }: { role: string }) {
  const colors = ROLE_COLORS[role] ?? ROLE_COLORS.system;
  const initial = ROLE_INITIAL[role] ?? role.slice(0, 2).toUpperCase();
  return (
    <div
      className={`flex-shrink-0 w-8 h-8 rounded-full ${colors.bg} ${colors.text} flex items-center justify-center text-[10px] font-bold uppercase`}
    >
      {initial}
    </div>
  );
}

function ToolCallBlock({ name, args }: { name: string; args: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1 rounded-lg border border-gray-200 bg-gray-50 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-gray-500 hover:bg-gray-100 transition-colors"
      >
        <Wrench size={12} className="text-gray-400 flex-shrink-0" />
        <span className="font-medium text-gray-600">{name}</span>
        {open ? (
          <ChevronDown size={12} className="ml-auto text-gray-400" />
        ) : (
          <ChevronRight size={12} className="ml-auto text-gray-400" />
        )}
      </button>
      {open && args != null && (
        <div className="px-3 py-2 border-t border-gray-200">
          <pre className="tool-output text-gray-600 max-h-32 overflow-auto">
            {typeof args === "string" ? args : JSON.stringify(args, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function ToolResultBlock({ success, output }: { success: boolean; output: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1 rounded-lg border border-gray-200 bg-gray-50 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs hover:bg-gray-100 transition-colors"
      >
        {success ? (
          <CheckCircle size={12} className="text-green-500 flex-shrink-0" />
        ) : (
          <XCircle size={12} className="text-red-500 flex-shrink-0" />
        )}
        <span className={`font-medium ${success ? "text-green-600" : "text-red-600"}`}>
          {success ? "Result: success" : "Result: failed"}
        </span>
        {open ? (
          <ChevronDown size={12} className="ml-auto text-gray-400" />
        ) : (
          <ChevronRight size={12} className="ml-auto text-gray-400" />
        )}
      </button>
      {open && output && (
        <div className="px-3 py-2 border-t border-gray-200">
          <pre className="tool-output text-gray-600 max-h-32 overflow-auto">{output}</pre>
        </div>
      )}
    </div>
  );
}

function ThinkingIndicator({ phase }: { phase: string }) {
  const label =
    phase === "planning"
      ? "Planning…"
      : phase === "executing"
      ? "Executing…"
      : phase === "reviewing"
      ? "Reviewing…"
      : "Working…";

  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
        <Sparkles size={14} className="text-emerald-600" />
      </div>
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
        <span className="text-sm text-gray-500 mr-1">{label}</span>
        <div className="flex items-center gap-1">
          <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-gray-400 inline-block" />
          <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-gray-400 inline-block" />
          <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-gray-400 inline-block" />
        </div>
      </div>
    </div>
  );
}

function ChatMessage({ msg }: { msg: MessageType }) {
  if (msg.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] bg-emerald-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 shadow-sm">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.text}</p>
        </div>
      </div>
    );
  }

  if (msg.kind === "status") {
    return (
      <div className="flex justify-center">
        <div className="flex items-center gap-1.5 text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
          <Zap size={10} />
          <span>{msg.text}</span>
        </div>
      </div>
    );
  }

  if (msg.kind === "error") {
    return (
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 flex items-center justify-center">
          <AlertCircle size={14} className="text-red-500" />
        </div>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-2xl rounded-tl-sm px-4 py-3 text-sm max-w-[75%]">
          {msg.text}
        </div>
      </div>
    );
  }

  if (msg.kind === "tool_call") {
    return (
      <div className="flex items-start gap-3">
        <RoleAvatar role={msg.role} />
        <div className="max-w-[75%] flex-1">
          <ToolCallBlock name={msg.name} args={msg.args} />
        </div>
      </div>
    );
  }

  if (msg.kind === "tool_result") {
    return (
      <div className="flex items-start gap-3">
        <div className="w-8 flex-shrink-0" />
        <div className="max-w-[75%] flex-1">
          <ToolResultBlock success={msg.success} output={msg.output} />
        </div>
      </div>
    );
  }

  // kind === "text"
  return (
    <div className="flex items-start gap-3">
      <RoleAvatar role={msg.role} />
      <div className="max-w-[75%] bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            {msg.role}
          </span>
        </div>
        <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{msg.text}</p>
      </div>
    </div>
  );
}

const SUGGESTED_PROMPTS = [
  "Review the codebase and suggest improvements",
  "Write unit tests for the core module",
  "Refactor the API layer for better error handling",
  "Create a performance optimization plan",
];

function CliRunBanner({ run }: { run: ActiveRun }) {
  return (
    <div className="flex items-center gap-2 text-xs text-violet-600 bg-violet-50 border border-violet-200 rounded-full px-3 py-1.5 mx-auto w-fit">
      <Terminal size={12} />
      <span className="font-medium">CLI run</span>
      <span className="text-violet-400 truncate max-w-[200px]">{run.prompt}</span>
    </div>
  );
}

export default function AgentConsole() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const {
    getSession,
    createSession,
    setActiveSession,
    updateSessionEvents,
    updateSessionTitle,
    updateSessionProjectDir,
    updateSessionTeam,
    updateSessionQuality,
    updateSessionSource,
    updateSessionStreaming,
  } = useChatSessions();

  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<MessageType[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [phase, setPhase] = useState<string>("working");
  const [cliRun, setCliRun] = useState<ActiveRun | null>(null);
  const [showDirPicker, setShowDirPicker] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const eventsRef = useRef<AgentEvent[]>([]);
  const subscribedRunRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | undefined>(sessionId);
  const pendingPromptRef = useRef<string>("");
  const pendingSessionIdRef = useRef<string>("");

  // Keep ref in sync for use in callbacks
  sessionIdRef.current = sessionId;

  // Sync messages from stored session when sessionId changes.
  // Note: setActiveSession is handled by ChatView when inside /chat/:sessionId,
  // or here for the root / landing page.
  useEffect(() => {
    if (!sessionId) {
      setActiveSession(null);
    }
    if (sessionId) {
      const session = getSession(sessionId);
      if (session && session.events.length > 0) {
        eventsRef.current = session.events;
        const userMsg: MessageType | null = session.prompt
          ? { kind: "user", text: session.prompt }
          : null;
        const built = buildMessages(session.events);
        setMessages(userMsg ? [userMsg, ...built] : built);
      } else {
        eventsRef.current = [];
        setMessages([]);
      }
    } else {
      eventsRef.current = [];
      setMessages([]);
    }
    setStreaming(false);
    setCliRun(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const handleEvent = useCallback((evt: AgentEvent) => {
    eventsRef.current = [...eventsRef.current, evt];
    setMessages((prev) => {
      const userMsg = prev.find((m) => m.kind === "user");
      const built = buildMessages(eventsRef.current);
      return userMsg ? [userMsg, ...built] : built;
    });
    const data = evt.data as Record<string, unknown> | undefined;
    if (evt.type === "status" && data?.phase) {
      setPhase(String(data.phase));
    }
    // Persist events to session store
    const sid = sessionIdRef.current;
    if (sid) {
      updateSessionEvents(sid, [...eventsRef.current]);
    }
  }, [updateSessionEvents]);

  // Poll for active CLI runs and auto-create chat sessions for them
  useEffect(() => {
    if (streaming) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const runs = await api.getActiveRuns();
        if (cancelled) return;
        const active = runs.find((r) => r.status === "running");
        if (active && active.run_id !== subscribedRunRef.current) {
          subscribedRunRef.current = active.run_id;

          const cliSessionId = createSession();
          updateSessionTitle(cliSessionId, deriveTitle(active.prompt || "CLI Run"));
          updateSessionSource(cliSessionId, "cli");
          updateSessionStreaming(cliSessionId, true);
          navigate(`/chat/${cliSessionId}`, { replace: true });

          setCliRun(active);
          eventsRef.current = [];
          setMessages([]);
          setStreaming(true);
          setPhase("working");
          sessionIdRef.current = cliSessionId;

          api.subscribeToRun(
            active.run_id,
            (evt: AgentEvent) => {
              eventsRef.current = [...eventsRef.current, evt];
              setMessages((prev) => {
                const userMsg = prev.find((m) => m.kind === "user");
                const built = buildMessages(eventsRef.current);
                return userMsg ? [userMsg, ...built] : built;
              });
              const data = evt.data as Record<string, unknown> | undefined;
              if (evt.type === "status" && data?.phase) {
                setPhase(String(data.phase));
              }
              updateSessionEvents(cliSessionId, [...eventsRef.current]);
            },
            () => {
              setStreaming(false);
              setCliRun(null);
              subscribedRunRef.current = null;
              updateSessionStreaming(cliSessionId, false);
            },
            (err) => {
              setMessages((prev) => [...prev, { kind: "error", text: err }]);
              setStreaming(false);
              setCliRun(null);
              subscribedRunRef.current = null;
              updateSessionStreaming(cliSessionId, false);
            }
          );
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
    };
  }, [streaming, createSession, updateSessionTitle, updateSessionSource, updateSessionStreaming, updateSessionEvents, navigate]);

  const startExecution = useCallback((targetSessionId: string, text: string, projectDir: string) => {
    updateSessionProjectDir(targetSessionId, projectDir);
    updateSessionStreaming(targetSessionId, true);

    api.getTeams().then((teams) => {
      if (teams[0]) updateSessionTeam(targetSessionId, teams[0]);
    }).catch(() => {});
    api.getQuality().then((q) => {
      updateSessionQuality(targetSessionId, q);
    }).catch(() => {});

    sessionIdRef.current = targetSessionId;
    setPrompt("");
    eventsRef.current = [];
    setCliRun(null);
    setMessages([{ kind: "user", text }]);
    setStreaming(true);
    setPhase("working");
    api.streamTeamEvents(
      "default",
      text,
      handleEvent,
      () => {
        setStreaming(false);
        updateSessionStreaming(targetSessionId, false);
      },
      (err) => {
        setMessages((prev) => [...prev, { kind: "error", text: err }]);
        setStreaming(false);
        updateSessionStreaming(targetSessionId, false);
      },
      projectDir
    );
  }, [handleEvent, updateSessionProjectDir, updateSessionTeam, updateSessionQuality, updateSessionStreaming]);

  const handleRun = () => {
    const text = prompt.trim();
    if (!text || streaming) return;

    let targetSessionId = sessionId;

    if (!targetSessionId) {
      targetSessionId = createSession();
      navigate(`/chat/${targetSessionId}`, { replace: true });
    }

    const session = getSession(targetSessionId);
    if (session && session.title === "New Chat") {
      updateSessionTitle(targetSessionId, deriveTitle(text));
    }

    // If this session already has a projectDir, skip the picker
    if (session?.projectDir) {
      startExecution(targetSessionId, text, session.projectDir);
      return;
    }

    // Show directory picker before first execution
    pendingPromptRef.current = text;
    pendingSessionIdRef.current = targetSessionId;
    setShowDirPicker(true);
  };

  const handleDirConfirm = (dir: string) => {
    setShowDirPicker(false);
    const sid = pendingSessionIdRef.current;
    const text = pendingPromptRef.current;
    if (sid && text) {
      startExecution(sid, text, dir);
    }
  };

  const handleDirCancel = () => {
    setShowDirPicker(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleRun();
    }
  };

  const handlePromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setPrompt(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
  };

  const isEmpty = messages.length === 0;
  const currentSession = sessionId ? getSession(sessionId) : undefined;

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {showDirPicker && (
        <DirectoryPicker onConfirm={handleDirConfirm} onCancel={handleDirCancel} />
      )}

      {/* Project dir badge */}
      {currentSession?.projectDir && (
        <div className="flex-shrink-0 px-4 py-2 border-b border-gray-200 bg-white">
          <div className="max-w-3xl mx-auto flex items-center gap-2 text-xs text-gray-500">
            <FolderOpen size={12} className="text-gray-400" />
            <span className="font-mono truncate">{currentSession.projectDir}</span>
          </div>
        </div>
      )}

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto chat-scroll px-4">
        {isEmpty ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-14 h-14 rounded-2xl bg-emerald-500 flex items-center justify-center mb-5 shadow-lg shadow-emerald-200">
              <Sparkles size={26} className="text-white" />
            </div>
            <h1 className="text-2xl font-semibold text-gray-900 mb-2">What can I help you build?</h1>
            <p className="text-gray-500 text-sm mb-8 max-w-sm">
              ch.ai orchestrates a team of specialized agents to tackle your engineering tasks.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {SUGGESTED_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => {
                    setPrompt(p);
                    inputRef.current?.focus();
                  }}
                  className="text-left rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-800 transition-all shadow-sm"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Messages */
          <div className="max-w-3xl mx-auto py-8 space-y-5">
            {cliRun && <CliRunBanner run={cliRun} />}
            {messages.map((msg, i) => (
              <ChatMessage key={i} msg={msg} />
            ))}
            {streaming && <ThinkingIndicator phase={phase} />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 px-4 pb-6 pt-3 bg-gray-50">
        <div className="max-w-3xl mx-auto">
          <div className="relative bg-white rounded-2xl border border-gray-200 shadow-sm focus-within:border-emerald-400 focus-within:shadow-md transition-all">
            <textarea
              ref={inputRef}
              value={prompt}
              onChange={handlePromptChange}
              onKeyDown={handleKeyDown}
              placeholder="Message ch.ai…"
              rows={1}
              disabled={streaming}
              className="w-full resize-none bg-transparent px-4 py-3.5 pr-14 text-sm text-gray-900 placeholder-gray-400 focus:outline-none disabled:opacity-60 max-h-[200px] leading-relaxed"
              style={{ height: "auto" }}
            />
            <button
              onClick={handleRun}
              disabled={!prompt.trim() || streaming}
              className="absolute right-2.5 bottom-2.5 w-9 h-9 flex items-center justify-center rounded-xl bg-emerald-600 text-white hover:bg-emerald-500 disabled:bg-gray-200 disabled:text-gray-400 transition-all"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
          <p className="text-center text-xs text-gray-400 mt-2">
            Press Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}
