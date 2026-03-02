import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import type { AgentEvent, Team, QualityScore } from "../api/client";

const STORAGE_KEY = "chai-chat-sessions";

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  events: AgentEvent[];
  prompt?: string;
  projectDir?: string;
  teamSnapshot?: Team;
  qualitySnapshot?: Record<string, QualityScore>;
  source?: "web" | "cli";
  streaming?: boolean;
  cliRunId?: string;
}

interface ChatSessionContextValue {
  sessions: ChatSession[];
  activeSessionId: string | null;
  createSession: () => string;
  setActiveSession: (id: string | null) => void;
  updateSessionEvents: (id: string, events: AgentEvent[]) => void;
  updateSessionTitle: (id: string, title: string) => void;
  updateSessionProjectDir: (id: string, projectDir: string) => void;
  updateSessionTeam: (id: string, team: Team) => void;
  updateSessionQuality: (id: string, quality: Record<string, QualityScore>) => void;
  updateSessionSource: (id: string, source: "web" | "cli") => void;
  updateSessionStreaming: (id: string, streaming: boolean) => void;
  updateSessionCliRunId: (id: string, cliRunId: string) => void;
  deleteSession: (id: string) => void;
  clearAllSessions: () => void;
  getSession: (id: string) => ChatSession | undefined;
}

const ChatSessionContext = createContext<ChatSessionContextValue | null>(null);

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ChatSession[];
  } catch {
    return [];
  }
}

function persistSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch {
    // localStorage may be full or unavailable
  }
}

function generateId(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2, 10);
}

export function deriveTitle(prompt: string): string {
  const trimmed = prompt.trim();
  if (trimmed.length <= 50) return trimmed;
  return trimmed.slice(0, 50) + "…";
}

function pruneStaleSessions(sessions: ChatSession[]): ChatSession[] {
  const ONE_DAY_MS = 24 * 60 * 60 * 1000;
  const now = Date.now();
  return sessions.filter((s) => {
    const isEmpty = s.events.length === 0 && s.title === "New Chat" && !s.prompt;
    if (isEmpty && now - s.createdAt > ONE_DAY_MS) return false;
    return true;
  });
}

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    const loaded = loadSessions();
    const cleaned = loaded.map((s) =>
      s.streaming ? { ...s, streaming: false } : s
    );
    return pruneStaleSessions(cleaned);
  });
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  useEffect(() => {
    persistSessions(sessions);
  }, [sessions]);

  const createSession = useCallback((): string => {
    const id = generateId();
    const session: ChatSession = {
      id,
      title: "New Chat",
      createdAt: Date.now(),
      events: [],
    };
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(id);
    return id;
  }, []);

  const setActiveSession = useCallback((id: string | null) => {
    setActiveSessionId(id);
  }, []);

  const updateSessionEvents = useCallback(
    (id: string, events: AgentEvent[]) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, events } : s))
      );
    },
    []
  );

  const updateSessionTitle = useCallback((id: string, title: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title, prompt: title } : s))
    );
  }, []);

  const updateSessionProjectDir = useCallback((id: string, projectDir: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, projectDir } : s))
    );
  }, []);

  const updateSessionTeam = useCallback((id: string, team: Team) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, teamSnapshot: team } : s))
    );
  }, []);

  const updateSessionQuality = useCallback(
    (id: string, quality: Record<string, QualityScore>) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, qualitySnapshot: quality } : s))
      );
    },
    []
  );

  const updateSessionSource = useCallback((id: string, source: "web" | "cli") => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, source } : s))
    );
  }, []);

  const updateSessionStreaming = useCallback((id: string, streaming: boolean) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, streaming } : s))
    );
  }, []);

  const updateSessionCliRunId = useCallback((id: string, cliRunId: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, cliRunId } : s))
    );
  }, []);

  const deleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
      }
    },
    [activeSessionId]
  );

  const clearAllSessions = useCallback(() => {
    setSessions([]);
    setActiveSessionId(null);
  }, []);

  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  const getSession = useCallback(
    (id: string) => sessionsRef.current.find((s) => s.id === id),
    []
  );

  return (
    <ChatSessionContext.Provider
      value={{
        sessions,
        activeSessionId,
        createSession,
        setActiveSession,
        updateSessionEvents,
        updateSessionTitle,
        updateSessionProjectDir,
        updateSessionTeam,
        updateSessionQuality,
        updateSessionSource,
        updateSessionStreaming,
        updateSessionCliRunId,
        deleteSession,
        clearAllSessions,
        getSession,
      }}
    >
      {children}
    </ChatSessionContext.Provider>
  );
}

export function useChatSessions(): ChatSessionContextValue {
  const ctx = useContext(ChatSessionContext);
  if (!ctx) {
    throw new Error("useChatSessions must be used within ChatSessionProvider");
  }
  return ctx;
}
