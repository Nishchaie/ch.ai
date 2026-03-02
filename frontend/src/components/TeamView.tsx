import { useEffect, useState } from "react";
import { api, type Team } from "../api/client";
import { useChatSessions } from "../store/chatSessions";
import { Spinner } from "./Spinner";
import { Activity } from "lucide-react";

const ROLE_STYLE: Record<string, { dot: string; bg: string; text: string; label: string }> = {
  lead: { dot: "bg-amber-500", bg: "bg-amber-50", text: "text-amber-700", label: "Team Lead" },
  frontend: { dot: "bg-cyan-500", bg: "bg-cyan-50", text: "text-cyan-700", label: "Frontend" },
  backend: { dot: "bg-green-500", bg: "bg-green-50", text: "text-green-700", label: "Backend" },
  prompt: { dot: "bg-fuchsia-500", bg: "bg-fuchsia-50", text: "text-fuchsia-700", label: "Prompt" },
  researcher: { dot: "bg-blue-500", bg: "bg-blue-50", text: "text-blue-700", label: "Researcher" },
  qa: { dot: "bg-red-500", bg: "bg-red-50", text: "text-red-700", label: "QA" },
  deployment: { dot: "bg-yellow-500", bg: "bg-yellow-50", text: "text-yellow-700", label: "Deployment" },
  custom: { dot: "bg-gray-400", bg: "bg-gray-50", text: "text-gray-600", label: "Custom" },
};

const DEFAULT_STYLE = { dot: "bg-gray-400", bg: "bg-gray-50", text: "text-gray-600", label: "Agent" };

const PROVIDER_DISPLAY: Record<string, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
  anthropic_api: "Anthropic API",
  openai_api: "OpenAI API",
  custom: "Custom",
};

function formatProvider(raw: string): string {
  return PROVIDER_DISPLAY[raw] ?? raw.replace(/_/g, " ");
}

function RoleCard({
  role,
  provider,
  model,
}: {
  role: string;
  provider?: string;
  model?: string;
}) {
  const style = ROLE_STYLE[role] ?? DEFAULT_STYLE;
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md hover:border-gray-300 transition-all">
      <div className="flex items-center gap-3 mb-3">
        <div
          className={`w-9 h-9 rounded-full ${style.bg} flex items-center justify-center`}
        >
          <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
        </div>
        <div>
          <div className={`text-sm font-semibold ${style.text}`}>{style.label}</div>
          <div className="text-xs text-gray-400 uppercase tracking-wide">{role}</div>
        </div>
      </div>
      <div className="space-y-1">
        {provider && (
          <div className="text-sm text-gray-600">
            <span className="text-gray-400 text-xs">Provider</span>
            <div className="font-medium">{formatProvider(provider)}</div>
          </div>
        )}
        {model && (
          <div className="text-xs text-gray-400 font-mono truncate" title={model}>
            {model}
          </div>
        )}
      </div>
    </div>
  );
}

function TeamGrid({ team, sessionTitle }: { team: Team; sessionTitle?: string }) {
  const members = team.members ?? {};
  const memberCount = Object.keys(members).length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Team Composition</h2>
        <p className="text-gray-500 text-sm mt-1">
          {sessionTitle && <span className="text-gray-400">{sessionTitle} · </span>}
          {memberCount > 0
            ? `${memberCount} agent${memberCount !== 1 ? "s" : ""} configured`
            : "No agents configured yet"}
        </p>
      </div>

      {memberCount > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {Object.entries(members).map(([role, info]) => {
            const obj = typeof info === "object" && info ? info : {};
            const prov = "provider" in obj && obj.provider != null ? String(obj.provider) : undefined;
            const mod = "model" in obj && obj.model != null ? String(obj.model) : undefined;
            return (
              <RoleCard
                key={role}
                role={role}
                provider={prov}
                model={mod}
              />
            );
          })}
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center shadow-sm">
          <p className="text-gray-500 text-sm">
            No team members configured. Run{" "}
            <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
              chai team create
            </code>{" "}
            to set up your team.
          </p>
        </div>
      )}
    </div>
  );
}

export default function TeamView() {
  const { activeSessionId, getSession } = useChatSessions();
  const activeSession = activeSessionId ? getSession(activeSessionId) : undefined;

  // If the active session has a team snapshot, show it
  if (activeSession?.teamSnapshot) {
    return <TeamGrid team={activeSession.teamSnapshot} sessionTitle={activeSession.title} />;
  }

  return <GlobalTeamView />;
}

function GlobalTeamView() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [teamsRes, statusRes] = await Promise.all([
          api.getTeams(),
          api.getTeamStatus("default").catch(() => null),
        ]);
        setTeams(teamsRes);
        setStatus(statusRes);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading team…" />
      </div>
    );
  }

  const team = teams[0] ?? { name: "default", members: {} };

  return (
    <div className="space-y-6">
      <TeamGrid team={team} />

      {status && (
        <div className="inline-flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-4 py-2.5 shadow-sm">
          <Activity size={14} className="text-emerald-500" />
          <span className="text-sm text-gray-500">Status:</span>
          <span className="text-sm font-semibold text-gray-900 capitalize">
            {(status.state as string) ?? "—"}
          </span>
        </div>
      )}
    </div>
  );
}
