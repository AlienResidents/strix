import { History, ChevronRight, Terminal } from "lucide-react";
import type { RunListEntry, RunsPayload, RunSeverityCounts } from "@/data/serverSource";

/**
 * "Past runs" panel. Unverified users see a tease with the run count and a
 * verify affordance (the launched run stays fully visible; the CLI
 * `strix view <name>` still works). Verified users get the full history and can
 * switch the active run, which threads ?run=<name> through the data fetches.
 */

const SEV = [
  { key: "critical", dot: "bg-red-500", text: "text-red-500" },
  { key: "high", dot: "bg-orange-500", text: "text-orange-500" },
  { key: "medium", dot: "bg-yellow-500", text: "text-yellow-500" },
  { key: "low", dot: "bg-blue-500", text: "text-blue-500" },
] as const;

function SeverityChips({ counts }: { counts: RunSeverityCounts }) {
  const shown = SEV.filter((s) => counts[s.key] > 0);
  if (shown.length === 0) {
    return <span className="text-xs text-[#555]">No findings</span>;
  }
  return (
    <div className="flex items-center gap-3">
      {shown.map((s) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden="true" />
          <span className={`text-xs tabular-nums ${s.text}`}>{counts[s.key]}</span>
        </div>
      ))}
    </div>
  );
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const normalized = iso.trim().replace(" UTC", "Z").replace(" ", "T");
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

interface PastRunsViewProps {
  runs: RunsPayload | null;
  activeRun: string | null;
  onSelectRun: (name: string) => void;
  onVerifyClick: () => void;
}

export default function PastRunsView({
  runs,
  activeRun,
  onSelectRun,
  onVerifyClick,
}: PastRunsViewProps) {
  const count = runs?.count ?? 0;

  if (!runs || runs.locked) {
    return (
      <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-8 text-center">
        <div
          className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl"
          style={{ border: "1px solid #2a2a2a", background: "rgba(255,255,255,0.04)" }}
        >
          <History className="h-5 w-5 text-[#888]" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold text-white">Browse every run on this machine</h2>
        <p className="mx-auto mt-1.5 max-w-md text-sm text-[#888]">
          You have {count} past {count === 1 ? "run" : "runs"} on this machine. Verify your
          email to browse them here.
        </p>
        <button
          onClick={onVerifyClick}
          className="mt-4 cursor-pointer rounded-lg bg-white px-4 py-2 text-sm font-semibold text-black transition-opacity hover:opacity-90"
        >
          Verify email to unlock
        </button>
        <p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-[#555]">
          <Terminal className="h-3.5 w-3.5" aria-hidden="true" />
          Or open one from the CLI with{" "}
          <code className="font-mono text-[#888]">strix view &lt;name&gt;</code>
        </p>
      </div>
    );
  }

  if (runs.runs.length === 0) {
    return (
      <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-8 text-center text-sm text-[#888]">
        No past runs found on this machine yet.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {runs.runs.map((run: RunListEntry) => {
        const active = run.name === activeRun;
        const date = formatDate(run.start_time) ?? formatDate(run.end_time);
        return (
          <button
            key={run.name}
            onClick={() => onSelectRun(run.name)}
            className={`group flex w-full cursor-pointer items-center gap-4 rounded-lg border px-4 py-3 text-left transition-colors ${
              active
                ? "border-[#444] bg-[rgba(255,255,255,0.04)]"
                : "border-[#222] bg-[rgba(255,255,255,0.02)] hover:border-[#444]"
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-white">{run.name}</span>
                {active && (
                  <span className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-400" style={{ border: "1px solid rgba(16,185,129,0.3)" }}>
                    Active
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[#666]">
                {run.target && <span className="truncate font-mono text-[#888]">{run.target}</span>}
                {run.target && (run.scan_mode || date || run.status) && <span className="text-[#333]">·</span>}
                {run.scan_mode && <span className="capitalize">{run.scan_mode}</span>}
                {date && <span className="text-[#333]">·</span>}
                {date && <span>{date}</span>}
                {run.status && <span className="text-[#333]">·</span>}
                {run.status && <span className="capitalize">{run.status}</span>}
              </div>
            </div>
            <SeverityChips counts={run.severity_counts} />
            <ChevronRight className="h-4 w-4 flex-shrink-0 text-[#555] transition-colors group-hover:text-[#aaa]" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
