export function Spinner({
  label,
  size = "md",
}: {
  label?: string;
  size?: "sm" | "md";
}) {
  const dim = size === "sm" ? "h-4 w-4" : "h-5 w-5";
  return (
    <div className="flex items-center gap-2">
      <div
        className={`animate-spin rounded-full border-2 border-gray-200 border-t-emerald-500 ${dim}`}
      />
      {label && <span className="text-gray-500 text-sm">{label}</span>}
    </div>
  );
}
