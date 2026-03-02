import { useRef, useEffect, useMemo, useState } from "react";
import { useChatSessions } from "../store/chatSessions";
import type { AgentEvent } from "../api/client";
import { Terminal, ChevronDown, ChevronRight, CheckCircle, XCircle, AlertCircle, Loader2 } from "lucide-react";

const ROLE_COLORS: Record<string, string> = {
  lead: "text-amber-400",
  frontend: "text-cyan-400",
  backend: "text-green-400",
  prompt: "text-fuchsia-400",
  researcher: "text-blue-400",
  qa: "text-red-400",
  deployment: "text-yellow-400",
  system: "text-gray-500",
};

interface LogEntry {
  index: number;
  type: string;
  role: string;
  summary: string;
  detail?: string;
  isError?: boolean;
  success?: boolean;
}

function buildLogEntries(events: AgentEvent[]): LogEntry[] {
  const entries: LogEntry[] = [];
  for (let i = 0; i < events.length; i++) {
    const evt = events[i];
    const role = evt.role ?? "system";
    const data = evt.data as Record<string, unknown> | undefined;

    if (evt.type === "text") {
      entries.push({
        index: i,
        type: "text",
        role,
        summary: String(evt.data).split("\n")[0].slice(0, 120),
        detail: String(evt.data),
      });
    } else if (evt.type === "tool_call") {
      const name = (data?.name as string) ?? "?";
      const argsStr = data?.args
        ? typeof data.args === "string"
          ? data.args
          : JSON.stringify(data.args, null, 2)
        : undefined;
      entries.push({
        index: i,
        type: "tool_call",
        role,
        summary: `tool_call: ${name}`,
        detail: argsStr,
      });
    } else if (evt.type === "tool_result") {
      const success = Boolean(data?.success);
      const output = String(data?.output ?? "");
      entries.push({
        index: i,
        type: "tool_result",
        role,
        summary: success ? "result: success" : "result: failed",
        detail: output,
        success,
      });
    } else if (evt.type === "status") {
      let text = "";
      if (data?.phase) text = `phase: ${data.phase}`;
      else if (data?.task_started) {
        const title = (data.title as string) ?? String(data.task_started);
        text = `task_started: ${title}`;
      } else if (data?.task_completed) text = "task_completed";
      else text = JSON.stringify(data);
      entries.push({ index: i, type: "status", role, summary: text });
    } else if (evt.type === "activity") {
      const msg = (data as { message?: string })?.message;
      if (msg) entries.push({ index: i, type: "activity", role, summary: msg });
    } else if (evt.type === "error") {
      entries.push({
        index: i,
        type: "error",
        role,
        summary: String(evt.data),
        isError: true,
      });
    } else if (evt.type === "info" && data && Array.isArray(data.tasks)) {
      entries.push({
        index: i,
        type: "info",
        role: "system",
        summary: `created ${(data.tasks as unknown[]).length} tasks`,
        detail: JSON.stringify(data.tasks, null, 2),
      });
    }
  }
  return entries;
}

function LogLine({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const roleColor = ROLE_COLORS[entry.role] ?? ROLE_COLORS.system;
  const hasDetail = Boolean(entry.detail);

  return (
    <div className="group">
      <div
        className={`flex items-start gap-2 px-3 py-1 font-mono text-xs leading-relaxed hover:bg-gray-800/60 transition-colors ${
          hasDetail ? "cursor-pointer" : ""
        }`}
        onClick={() => hasDetail && setExpanded((v) => !v)}
      >
        <span className="text-gray-600 select-none w-8 text-right flex-shrink-0">
          {entry.index + 1}
        </span>

        {hasDetail ? (
          expanded ? (
            <ChevronDown size={10} className="text-gray-600 mt-0.5 flex-shrink-0" />
          ) : (
            <ChevronRight size={10} className="text-gray-600 mt-0.5 flex-shrink-0" />
          )
        ) : (
          <span className="w-[10px] flex-shrink-0" />
        )}

        <span className={`flex-shrink-0 w-16 text-right ${roleColor}`}>
          {entry.role}
        </span>

        <span className="text-gray-500 flex-shrink-0">|</span>

        {entry.isError ? (
          <span className="flex items-center gap-1 text-red-400">
            <AlertCircle size={10} className="flex-shrink-0" />
            {entry.summary}
          </span>
        ) : entry.type === "tool_result" ? (
          <span className={`flex items-center gap-1 ${entry.success ? "text-green-400" : "text-red-400"}`}>
            {entry.success ? <CheckCircle size={10} className="flex-shrink-0" /> : <XCircle size={10} className="flex-shrink-0" />}
            {entry.summary}
          </span>
        ) : (
          <span className="text-gray-300">{entry.summary}</span>
        )}
      </div>

      {expanded && entry.detail && (
        <pre className="ml-[6.5rem] px-3 py-2 text-xs text-gray-400 bg-gray-800/40 border-l-2 border-gray-700 max-h-48 overflow-auto whitespace-pre-wrap break-words">
          {entry.detail}
        </pre>
      )}
    </div>
  );
}

export default function ConsoleOutput() {
  const { activeSessionId, getSession, sessions } = useChatSessions();
  const bottomRef = useRef<HTMLDivElement>(null);

  const session = activeSessionId ? getSession(activeSessionId) : undefined;
  const entries = useMemo(
    () => (session ? buildLogEntries(session.events) : []),
    [session]
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  const isStreaming = session?.streaming ?? false;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Terminal size={20} className="text-gray-500" />
          <h2 className="text-2xl font-bold text-gray-900">Console Output</h2>
          {isStreaming && (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full">
              <Loader2 size={10} className="animate-spin" />
              Running
            </span>
          )}
        </div>
        <p className="text-gray-500 text-sm">
          {session
            ? `${entries.length} event${entries.length !== 1 ? "s" : ""} from: ${session.title}`
            : "Select a chat session to view its console output"}
        </p>
      </div>

      {!session ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center shadow-sm">
          {sessions.length === 0 ? (
            <p className="text-gray-500 text-sm">
              No chat sessions yet. Start a chat to see console output here.
            </p>
          ) : (
            <p className="text-gray-500 text-sm">
              Click on a chat session in the sidebar to view its console output.
            </p>
          )}
        </div>
      ) : entries.length === 0 && !isStreaming ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center shadow-sm">
          <p className="text-gray-500 text-sm">
            No events recorded for this session yet.
          </p>
        </div>
      ) : (
        <div className="bg-gray-900 rounded-xl border border-gray-700 overflow-hidden shadow-lg">
          {/* Terminal title bar */}
          <div className="flex items-center gap-2 px-4 py-2 bg-gray-800 border-b border-gray-700">
            <div className="flex gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-full ${isStreaming ? "bg-red-500 animate-pulse" : "bg-red-500/80"}`} />
              <span className={`w-2.5 h-2.5 rounded-full ${isStreaming ? "bg-yellow-500 animate-pulse" : "bg-yellow-500/80"}`} />
              <span className={`w-2.5 h-2.5 rounded-full ${isStreaming ? "bg-green-500 animate-pulse" : "bg-green-500/80"}`} />
            </div>
            <span className="text-xs text-gray-500 font-mono ml-2 truncate flex-1">
              {session.title}
              {session.projectDir && ` — ${session.projectDir}`}
            </span>
            {isStreaming && (
              <Loader2 size={12} className="text-emerald-400 animate-spin flex-shrink-0" />
            )}
          </div>

          {/* Log lines */}
          <div className="max-h-[600px] overflow-y-auto py-2 custom-scroll">
            {entries.map((entry) => (
              <LogLine key={entry.index} entry={entry} />
            ))}
            {isStreaming && (
              <div className="flex items-center gap-2 px-3 py-2 font-mono text-xs">
                <span className="text-gray-600 select-none w-8 text-right flex-shrink-0" />
                <span className="w-[10px] flex-shrink-0" />
                <span className="w-16 flex-shrink-0" />
                <span className="text-gray-500 flex-shrink-0" />
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <Loader2 size={10} className="animate-spin" />
                  processing...
                  <span className="inline-block w-1.5 h-3.5 bg-emerald-400 animate-pulse" />
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
    </div>
  );
}
