import { useEffect, useState } from "react";
import { api, type QualityScore } from "../api/client";
import { useChatSessions } from "../store/chatSessions";
import { BarChart2 } from "lucide-react";

const GRADE_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  A: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200" },
  B: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" },
  C: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200" },
  D: { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200" },
  F: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" },
};

const DEFAULT_GRADE_STYLE = { bg: "bg-gray-50", text: "text-gray-600", border: "border-gray-200" };

const SCORE_BAR_COLOR = (score: number) => {
  if (score >= 0.85) return "bg-emerald-500";
  if (score >= 0.7) return "bg-blue-500";
  if (score >= 0.5) return "bg-amber-500";
  return "bg-red-500";
};

function ScoresView({ scores, sessionTitle }: { scores: Record<string, QualityScore>; sessionTitle?: string }) {
  const entries = Object.entries(scores);

  if (entries.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Quality Dashboard</h2>
          <p className="text-gray-500 text-sm mt-1">
            {sessionTitle ? `${sessionTitle} · ` : ""}Code quality scores by domain
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center shadow-sm">
          <BarChart2 size={32} className="mx-auto text-gray-300 mb-3" />
          <p className="text-gray-500 text-sm">
            No quality scores yet. Run{" "}
            <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
              chai quality
            </code>{" "}
            from the CLI.
          </p>
        </div>
      </div>
    );
  }

  const avgScore =
    entries.reduce((sum, [, info]) => sum + (info.score ?? 0), 0) / entries.length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Quality Dashboard</h2>
        <p className="text-gray-500 text-sm mt-1">
          {sessionTitle && <span className="text-gray-400">{sessionTitle} · </span>}
          Overall average: {(avgScore * 100).toFixed(1)}%
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Overall Quality</span>
          <span className="text-sm font-bold text-gray-900">{(avgScore * 100).toFixed(1)}%</span>
        </div>
        <div className="h-3 rounded-full bg-gray-100 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${SCORE_BAR_COLOR(avgScore)}`}
            style={{ width: `${(avgScore ?? 0) * 100}%` }}
          />
        </div>
      </div>

      <div className="space-y-3">
        {entries.map(([domain, info]) => {
          const gradeStyle = GRADE_STYLE[info.grade?.charAt(0).toUpperCase() ?? ""] ?? DEFAULT_GRADE_STYLE;
          const pct = (info.score ?? 0) * 100;
          return (
            <div
              key={domain}
              className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-all"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="font-medium text-gray-900 capitalize">{domain}</span>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">{pct.toFixed(1)}%</span>
                  <span
                    className={`inline-flex items-center justify-center w-8 h-8 rounded-full border text-xs font-bold ${gradeStyle.bg} ${gradeStyle.text} ${gradeStyle.border}`}
                  >
                    {info.grade}
                  </span>
                </div>
              </div>
              <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${SCORE_BAR_COLOR(info.score ?? 0)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function QualityDashboard() {
  const { activeSessionId, getSession } = useChatSessions();
  const activeSession = activeSessionId ? getSession(activeSessionId) : undefined;

  if (activeSession?.qualitySnapshot) {
    return <ScoresView scores={activeSession.qualitySnapshot} sessionTitle={activeSession.title} />;
  }

  return <GlobalQualityDashboard />;
}

function GlobalQualityDashboard() {
  const [scores, setScores] = useState<Record<string, QualityScore>>({});

  useEffect(() => {
    api.getQuality().then(setScores);
  }, []);

  return <ScoresView scores={scores} />;
}
