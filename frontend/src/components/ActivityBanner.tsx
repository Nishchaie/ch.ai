const PHASE_CONFIG: Record<string, { label: string; dot: string; border: string; bg: string; text: string }> = {
  planning: {
    label: "Planning",
    dot: "bg-amber-400",
    border: "border-amber-200",
    bg: "bg-amber-50",
    text: "text-amber-700",
  },
  executing: {
    label: "Executing",
    dot: "bg-emerald-400",
    border: "border-emerald-200",
    bg: "bg-emerald-50",
    text: "text-emerald-700",
  },
  reviewing: {
    label: "Reviewing",
    dot: "bg-blue-400",
    border: "border-blue-200",
    bg: "bg-blue-50",
    text: "text-blue-700",
  },
};

const FALLBACK = {
  label: "Working",
  dot: "bg-gray-400",
  border: "border-gray-200",
  bg: "bg-gray-50",
  text: "text-gray-600",
};

export function ActivityBanner({
  phase,
  detail,
}: {
  phase: string;
  detail?: string;
}) {
  const cfg = PHASE_CONFIG[phase] ?? FALLBACK;

  return (
    <div
      className={`rounded-xl border ${cfg.border} ${cfg.bg} px-4 py-3 flex items-start gap-3 shadow-sm`}
    >
      <span
        className={`mt-1 inline-block h-2 w-2 rounded-full ${cfg.dot} animate-pulse-dot flex-shrink-0`}
      />
      <div className="min-w-0">
        <div className={`text-sm font-semibold ${cfg.text}`}>{cfg.label}…</div>
        {detail && (
          <div className="text-xs text-gray-500 truncate mt-0.5">{detail}</div>
        )}
      </div>
    </div>
  );
}
