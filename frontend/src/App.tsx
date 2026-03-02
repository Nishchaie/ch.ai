import { useState, useRef, useEffect } from "react";
import { Routes, Route, NavLink, useNavigate, useParams } from "react-router-dom";
import {
  Users,
  Kanban,
  FileText,
  BarChart2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Sparkles,
  MessageSquare,
  Trash2,
  Terminal,
} from "lucide-react";
import TeamView from "./components/TeamView";
import TaskBoard from "./components/TaskBoard";
import AgentConsole from "./components/AgentConsole";
import PlanViewer from "./components/PlanViewer";
import PlanDetail from "./components/PlanDetail";
import QualityDashboard from "./components/QualityDashboard";
import ConsoleOutput from "./components/ConsoleOutput";
import { ChatSessionProvider, useChatSessions } from "./store/chatSessions";

const NAV_ITEMS = [
  { to: "/", icon: MessageSquare, label: "Chat", exact: true },
  { to: "/console", icon: Terminal, label: "Console" },
  { to: "/team", icon: Users, label: "Team" },
  { to: "/tasks", icon: Kanban, label: "Tasks" },
  { to: "/plans", icon: FileText, label: "Plans" },
  { to: "/quality", icon: BarChart2, label: "Quality" },
];

function EditableTitle({
  value,
  onSave,
}: {
  value: string;
  onSave: (newTitle: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const commit = () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      onSave(trimmed);
    } else {
      setDraft(value);
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") { setDraft(value); setEditing(false); }
        }}
        onClick={(e) => e.stopPropagation()}
        className="truncate flex-1 text-xs bg-gray-600 text-white rounded px-1 py-0.5 outline-none border border-gray-500 focus:border-emerald-400"
      />
    );
  }

  return (
    <span
      className="truncate flex-1 text-xs"
      onDoubleClick={(e) => {
        e.stopPropagation();
        setDraft(value);
        setEditing(true);
      }}
      title="Double-click to rename"
    >
      {value}
    </span>
  );
}

function ChatHistoryList({ collapsed }: { collapsed: boolean }) {
  const { sessions, activeSessionId, deleteSession, updateSessionTitle } = useChatSessions();
  const navigate = useNavigate();

  if (sessions.length === 0 || collapsed) return null;

  return (
    <div className="px-2 mt-1">
      <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-3 mb-1">
        Recent
      </div>
      <div className="space-y-0.5 max-h-[280px] overflow-y-auto sidebar-scroll">
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`group flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer transition-colors ${
              s.id === activeSessionId
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:text-gray-100 hover:bg-gray-700/50"
            }`}
            onClick={() => navigate(`/chat/${s.id}`)}
          >
            <EditableTitle
              value={s.title}
              onSave={(newTitle) => updateSessionTitle(s.id, newTitle)}
            />
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteSession(s.id);
                if (s.id === activeSessionId) navigate("/");
              }}
              className="flex-shrink-0 p-0.5 rounded opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function AppContent() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const { createSession } = useChatSessions();

  const handleNewChat = () => {
    const id = createSession();
    navigate(`/chat/${id}`);
  };

  return (
    <div className="flex h-screen bg-white overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`flex flex-col bg-gray-900 text-gray-100 flex-shrink-0 sidebar-transition ${
          collapsed ? "w-[60px]" : "w-[240px]"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-4 border-b border-gray-700/50">
          {!collapsed && (
            <div className="flex items-center gap-2 min-w-0">
              <div className="flex-shrink-0 w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center">
                <Sparkles size={14} className="text-white" />
              </div>
              <span className="font-semibold text-white text-sm truncate">ch.ai</span>
            </div>
          )}
          {collapsed && (
            <div className="mx-auto w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center">
              <Sparkles size={14} className="text-white" />
            </div>
          )}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className={`flex-shrink-0 p-1.5 rounded-md text-gray-400 hover:text-gray-100 hover:bg-gray-700/50 transition-colors ${
              collapsed ? "hidden" : ""
            }`}
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        {/* New Chat button */}
        <div className="px-2 py-3">
          <button
            onClick={handleNewChat}
            className={`w-full flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-gray-300 border border-gray-600/60 hover:bg-gray-700/50 hover:text-white transition-all ${
              collapsed ? "justify-center px-2" : ""
            }`}
          >
            <Plus size={16} className="flex-shrink-0" />
            {!collapsed && <span>New Chat</span>}
          </button>
        </div>

        {/* Toggle open button when collapsed */}
        {collapsed && (
          <button
            onClick={() => setCollapsed(false)}
            className="mx-auto mb-2 p-1.5 rounded-md text-gray-400 hover:text-gray-100 hover:bg-gray-700/50 transition-colors"
          >
            <PanelLeftOpen size={16} />
          </button>
        )}

        {/* Chat history */}
        <ChatHistoryList collapsed={collapsed} />

        {/* Nav links */}
        <nav className="flex-1 px-2 space-y-0.5 custom-scroll overflow-y-auto sidebar-scroll mt-2">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-3 mb-1">
            Views
          </div>
          {NAV_ITEMS.filter((n) => n.to !== "/").map(({ to, icon: Icon, label, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  collapsed ? "justify-center px-2" : ""
                } ${
                  isActive
                    ? "bg-gray-700 text-white font-medium"
                    : "text-gray-400 hover:text-gray-100 hover:bg-gray-700/50"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    size={17}
                    className={`flex-shrink-0 ${isActive ? "text-emerald-400" : ""}`}
                  />
                  {!collapsed && <span>{label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        {!collapsed && (
          <div className="px-4 py-3 border-t border-gray-700/50">
            <p className="text-xs text-gray-500">AI Engineering Harness</p>
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col bg-gray-50 min-w-0 overflow-hidden">
        <Routes>
          <Route path="/" element={<AgentConsole />} />
          <Route path="/chat/:sessionId" element={<AgentConsole />} />
          <Route path="/console" element={<PageWrapper><ConsoleOutput /></PageWrapper>} />
          <Route path="/team" element={<PageWrapper><TeamView /></PageWrapper>} />
          <Route path="/tasks" element={<PageWrapper><TaskBoard /></PageWrapper>} />
          <Route path="/plans" element={<PageWrapper><PlanViewer /></PageWrapper>} />
          <Route path="/plans/:filename" element={<PageWrapper><PlanDetailRoute /></PageWrapper>} />
          <Route path="/quality" element={<PageWrapper><QualityDashboard /></PageWrapper>} />
        </Routes>
      </main>
    </div>
  );
}

function PlanDetailRoute() {
  const { filename } = useParams<{ filename: string }>();
  if (!filename) return null;
  return <PlanDetail filename={decodeURIComponent(filename)} />;
}

function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto custom-scroll">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {children}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ChatSessionProvider>
      <AppContent />
    </ChatSessionProvider>
  );
}
