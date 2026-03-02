import { useState, useEffect, useRef } from "react";
import { FolderOpen, Play, X } from "lucide-react";
import { api } from "../api/client";

interface DirectoryPickerProps {
  onConfirm: (projectDir: string) => void;
  onCancel: () => void;
}

export default function DirectoryPicker({ onConfirm, onCancel }: DirectoryPickerProps) {
  const [dir, setDir] = useState("");
  const [loading, setLoading] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getProjectDir()
      .then((d) => {
        setDir(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  const handleSubmit = () => {
    const trimmed = dir.trim();
    if (trimmed) onConfirm(trimmed);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl border border-gray-200 w-full max-w-md mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <FolderOpen size={18} className="text-emerald-600" />
            <h3 className="text-sm font-semibold text-gray-900">Working Directory</h3>
          </div>
          <button
            onClick={onCancel}
            className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-xs text-gray-500">
            Confirm or change the directory this chat session will operate in.
          </p>
          <input
            ref={inputRef}
            type="text"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
            placeholder={loading ? "Loading…" : "/path/to/project"}
            disabled={loading}
            className="w-full px-3 py-2.5 text-sm font-mono border border-gray-200 rounded-lg bg-gray-50 focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-200 disabled:opacity-50 transition-all"
          />
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs font-medium text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!dir.trim() || loading}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-500 disabled:bg-gray-300 disabled:text-gray-500 transition-colors"
          >
            <Play size={12} />
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
