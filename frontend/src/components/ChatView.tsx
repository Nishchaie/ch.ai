import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { MessageSquare, Terminal, Kanban, Users, BarChart2 } from "lucide-react";
import { useChatSessions } from "../store/chatSessions";
import AgentConsole from "./AgentConsole";
import ConsoleOutput from "./ConsoleOutput";
import TaskBoard from "./TaskBoard";
import TeamView from "./TeamView";
import QualityDashboard from "./QualityDashboard";

type ChatTab = "chat" | "console" | "tasks" | "team" | "quality";

const TABS: { id: ChatTab; label: string; icon: typeof MessageSquare }[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "console", label: "Console", icon: Terminal },
  { id: "tasks", label: "Tasks", icon: Kanban },
  { id: "team", label: "Team", icon: Users },
  { id: "quality", label: "Quality", icon: BarChart2 },
];

function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto custom-scroll">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {children}
      </div>
    </div>
  );
}

export default function ChatView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { setActiveSession } = useChatSessions();
  const [activeTab, setActiveTab] = useState<ChatTab>("chat");

  useEffect(() => {
    setActiveSession(sessionId ?? null);
  }, [sessionId, setActiveSession]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 border-b border-gray-200 bg-white px-6">
        <div className="flex items-center gap-2">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 px-5 py-3.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === id
                  ? "border-emerald-500 text-emerald-700"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              <Icon size={18} />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col">
        {activeTab === "chat" && <AgentConsole />}
        {activeTab === "console" && (
          <PageWrapper><ConsoleOutput /></PageWrapper>
        )}
        {activeTab === "tasks" && (
          <PageWrapper><TaskBoard /></PageWrapper>
        )}
        {activeTab === "team" && (
          <PageWrapper><TeamView /></PageWrapper>
        )}
        {activeTab === "quality" && (
          <PageWrapper><QualityDashboard /></PageWrapper>
        )}
      </div>
    </div>
  );
}
