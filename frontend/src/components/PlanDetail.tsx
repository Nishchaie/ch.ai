import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type PlanDetail as PlanDetailType, type PlanTask } from "../api/client";
import { Spinner } from "./Spinner";
import {
  ArrowLeft,
  FileText,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  ChevronRight,
  Circle,
} from "lucide-react";

const STATUS_CONFIG: Record<string, { icon: React.ReactNode; badge: string }> = {
  pending: {
    icon: <Clock size={12} />,
    badge: "bg-gray-50 text-gray-600 border-gray-200",
  },
  in_progress: {
    icon: <Loader2 size={12} className="animate-spin" />,
    badge: "bg-blue-50 text-blue-700 border-blue-200",
  },
  reviewing: {
    icon: <RotateCcw size={12} />,
    badge: "bg-amber-50 text-amber-700 border-amber-200",
  },
  completed: {
    icon: <CheckCircle2 size={12} />,
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  failed: {
    icon: <XCircle size={12} />,
    badge: "bg-red-50 text-red-700 border-red-200",
  },
};

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
const DEFAULT_STATUS = { icon: <Circle size={12} />, badge: DEFAULT_BADGE };

function TaskRow({ task }: { task: PlanTask }) {
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[task.status] ?? DEFAULT_STATUS;
  const roleBadge = ROLE_BADGE[task.role] ?? DEFAULT_BADGE;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-all">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 p-4 text-left"
      >
        <ChevronRight
          size={14}
          className={`text-gray-400 flex-shrink-0 transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{task.title}</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${roleBadge}`}
          >
            {task.role}
          </span>
          <span
            className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${statusCfg.badge}`}
          >
            {statusCfg.icon}
            {task.status.replace("_", " ")}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-0 ml-7 space-y-3 border-t border-gray-100 mt-0 pt-3">
          {task.description && (
            <p className="text-sm text-gray-600">{task.description}</p>
          )}
          {task.dependencies.length > 0 && (
            <div className="text-xs text-gray-400">
              <span className="font-medium text-gray-500">Depends on:</span>{" "}
              {task.dependencies.join(", ")}
            </div>
          )}
          {task.acceptance_criteria.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Acceptance criteria:</p>
              <ul className="space-y-0.5">
                {task.acceptance_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                    <span className="text-gray-300 mt-0.5">-</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PlanDetail({ filename }: { filename: string }) {
  const [plan, setPlan] = useState<PlanDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getPlanDetail(filename)
      .then(setPlan)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filename]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading plan…" />
      </div>
    );
  }

  if (error || !plan) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => navigate("/plans")}
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft size={14} />
          Back to plans
        </button>
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-600 text-sm">{error || "Plan not found"}</p>
        </div>
      </div>
    );
  }

  const statusCounts = plan.tasks.reduce(
    (acc, t) => {
      acc[t.status] = (acc[t.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate("/plans")}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
      >
        <ArrowLeft size={14} />
        Back to plans
      </button>

      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-11 h-11 rounded-xl bg-emerald-50 flex items-center justify-center">
          <FileText size={20} className="text-emerald-600" />
        </div>
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{plan.title}</h2>
          {plan.description && (
            <p className="text-gray-500 text-sm mt-1">{plan.description}</p>
          )}
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs text-gray-400 font-mono">{plan.filename}</span>
            <span className="text-xs text-gray-400">
              {plan.tasks.length} task{plan.tasks.length !== 1 ? "s" : ""}
            </span>
            {Object.entries(statusCounts).map(([status, count]) => {
              const cfg = STATUS_CONFIG[status] ?? DEFAULT_STATUS;
              return (
                <span
                  key={status}
                  className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${cfg.badge}`}
                >
                  {count} {status.replace("_", " ")}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {plan.tasks.map((task) => (
          <TaskRow key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
}
