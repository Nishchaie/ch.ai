import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, type AgentEvent } from "../api/client";
import { useChatSessions, deriveTitle } from "../store/chatSessions";

/**
 * App-level hook that polls for active CLI runs and subscribes to their
 * event streams.  Lives in AppContent so it survives route changes.
 *
 * Must be StrictMode-safe: if the effect re-runs after cleanup tore down
 * the WebSocket, we re-subscribe to the existing session rather than
 * creating a duplicate.
 */
export function useCliRunWatcher() {
  const navigate = useNavigate();
  const {
    sessions,
    createSession,
    updateSessionEvents,
    updateSessionTitle,
    updateSessionSource,
    updateSessionStreaming,
    updateSessionCliRunId,
  } = useChatSessions();

  const subscribedRunRef = useRef<string | null>(null);
  const disconnectRef = useRef<(() => void) | null>(null);
  const eventsRef = useRef<AgentEvent[]>([]);
  const sessionIdRef = useRef<string | null>(null);

  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  useEffect(() => {
    let cancelled = false;

    function subscribeToRun(runId: string, targetSessionId: string) {
      disconnectRef.current = api.subscribeToRun(
        runId,
        (evt: AgentEvent) => {
          eventsRef.current = [...eventsRef.current, evt];
          updateSessionEvents(targetSessionId, [...eventsRef.current]);
        },
        () => {
          updateSessionStreaming(targetSessionId, false);
          disconnectRef.current = null;
        },
        () => {
          updateSessionStreaming(targetSessionId, false);
          disconnectRef.current = null;
        },
      );
    }

    const poll = async () => {
      if (disconnectRef.current) return;

      try {
        const runs = await api.getActiveRuns();
        if (cancelled) return;
        const active = runs.find((r) => r.status === "running");
        if (!active) return;

        // Already handled this run — but the subscription may have been
        // torn down (e.g. StrictMode cleanup).  Re-subscribe if needed.
        if (active.run_id === subscribedRunRef.current) {
          const existingSession = sessionsRef.current.find(
            (s) => s.cliRunId === active.run_id,
          );
          if (existingSession && !disconnectRef.current) {
            sessionIdRef.current = existingSession.id;
            updateSessionStreaming(existingSession.id, true);
            subscribeToRun(active.run_id, existingSession.id);
          }
          return;
        }

        // Deduplicate: if a session already tracks this run, adopt it
        const alreadyTracked = sessionsRef.current.find(
          (s) => s.cliRunId === active.run_id,
        );
        if (alreadyTracked) {
          subscribedRunRef.current = active.run_id;
          sessionIdRef.current = alreadyTracked.id;
          if (!disconnectRef.current) {
            updateSessionStreaming(alreadyTracked.id, true);
            subscribeToRun(active.run_id, alreadyTracked.id);
          }
          return;
        }

        // New run — create a session
        subscribedRunRef.current = active.run_id;
        eventsRef.current = [];

        const cliSessionId = createSession();
        sessionIdRef.current = cliSessionId;
        updateSessionTitle(cliSessionId, deriveTitle(active.prompt || "CLI Run"));
        updateSessionSource(cliSessionId, "cli");
        updateSessionStreaming(cliSessionId, true);
        updateSessionCliRunId(cliSessionId, active.run_id);

        navigate(`/chat/${cliSessionId}`, { replace: true });

        subscribeToRun(active.run_id, cliSessionId);
      } catch {
        // API server may not be reachable
      }
    };

    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
      if (disconnectRef.current) {
        disconnectRef.current();
        disconnectRef.current = null;
      }
    };
  }, [createSession, updateSessionTitle, updateSessionSource, updateSessionStreaming, updateSessionCliRunId, updateSessionEvents, navigate]);
}
