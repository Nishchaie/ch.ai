import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Plan } from "../api/client";
import { Spinner } from "./Spinner";
import { FileText, ListChecks } from "lucide-react";

export default function PlanViewer() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.getPlans().then(setPlans).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading plans…" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Execution Plans</h2>
        <p className="text-gray-500 text-sm mt-1">
          {plans.length > 0
            ? `${plans.length} plan${plans.length !== 1 ? "s" : ""} available`
            : "No plans created yet"}
        </p>
      </div>

      {plans.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center shadow-sm">
          <FileText size={32} className="mx-auto text-gray-300 mb-3" />
          <p className="text-gray-500 text-sm">
            No plans yet. Run{" "}
            <code className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-xs font-mono">
              chai plan create "your prompt"
            </code>{" "}
            to create one.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((p) => (
            <div
              key={p.path}
              onClick={() => navigate(`/plans/${encodeURIComponent(p.filename)}`)}
              className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md hover:border-emerald-300 transition-all cursor-pointer"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center mt-0.5">
                    <FileText size={16} className="text-emerald-600" />
                  </div>
                  <div className="min-w-0">
                    <div className="font-semibold text-gray-900 text-sm">{p.title}</div>
                    <div className="text-xs text-gray-400 font-mono truncate mt-0.5" title={p.path}>
                      {p.filename}
                    </div>
                  </div>
                </div>
                <div className="flex-shrink-0 flex items-center gap-1.5 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-3 py-1 text-xs font-medium">
                  <ListChecks size={12} />
                  <span>{p.task_count} task{p.task_count !== 1 ? "s" : ""}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
