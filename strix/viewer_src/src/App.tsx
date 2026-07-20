import { useEffect, useMemo, useRef, useState } from "react";
import {
  ShieldCheck,
  ArrowLeft,
  Lock,
  GitPullRequest,
  CalendarClock,
  Rocket,
  AlertCircle,
  Waypoints,
} from "lucide-react";
import type { Vulnerability, VulnerabilitySeverity } from "@/types/issues";
import { SEVERITY_COLORS } from "@/types/issues";
import { getSeverityDot } from "@/lib/vulnerability-utils";
import VulnerabilityDetail from "@/components/vulnerability/VulnerabilityDetail";
import { ContentSection } from "@/components/vulnerability/ContentSection";
import { IssueSeveritySummary } from "@/components/IssueSeveritySummary";
import AgentGraph from "@/components/live/AgentGraph";
import { buildGraphAgents } from "@/components/live/AgentTranscript";
import AgentDetailModal from "@/components/live/AgentDetailModal";
import { severityCounts, type ParsedRunSummary } from "@/lib/local-run-parser";
import { fetchAll, fetchRunSummary, fetchTranscript, fetchVulnerabilities, type LoadedRun } from "@/data/serverSource";
import { SIGNUP_URL, trackCta } from "@/lib/cta";

const TRUST_BANNER =
  "Your findings stay on your machine. They're rendered here locally in your browser and never uploaded or stored by Strix.";

const SEVERITY_ORDER: VulnerabilitySeverity[] = ["critical", "high", "medium", "low"];
const POLL_MS = 500;

export default function App() {
  const [run, setRun] = useState<LoadedRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"overview" | "issues" | "agents">("overview");

  // Live polling. On mount fetch everything; while the run is unfinished, poll
  // /api/run each second and refresh transcript + vulnerabilities; once
  // finished, do one final full fetch and stop.
  const finishedRef = useRef(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = () => {
      timer = setTimeout(tick, POLL_MS);
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const { summary, raw, finished } = await fetchRunSummary();
        if (cancelled) return;
        if (finished && !finishedRef.current) {
          finishedRef.current = true;
          const full = await fetchAll();
          if (!cancelled) setRun(full);
          return; // stop polling
        }
        const [transcript, vulnerabilities] = await Promise.all([
          fetchTranscript().catch(() => ({ agents: [], events: [] })),
          fetchVulnerabilities(summary.runId).catch(() => [] as Vulnerability[]),
        ]);
        if (cancelled) return;
        setRun((prev) => ({
          summary,
          raw,
          finished,
          transcript,
          vulnerabilities,
          reportMarkdown: prev?.reportMarkdown ?? null,
        }));
        schedule();
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load run data.");
        schedule();
      }
    };

    (async () => {
      try {
        const full = await fetchAll();
        if (cancelled) return;
        setRun(full);
        if (full.finished) {
          finishedRef.current = true;
        } else {
          schedule();
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load run data.");
        schedule();
      }
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const counts = useMemo(
    () => (run ? severityCounts(run.vulnerabilities) : null),
    [run]
  );
  const selected = run?.vulnerabilities.find((v) => v.id === selectedId) ?? null;
  const agentCount = run?.transcript.agents.length ?? 0;

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Top bar */}
      <div className="border-b border-[#222]">
        <div className="max-w-[88rem] mx-auto px-6 py-4 flex items-center gap-1.5">
          <a
            href="https://app.strix.ai"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackCta("logo")}
            className="flex items-center gap-1.5 opacity-90 transition-opacity hover:opacity-100"
            title="Open Strix Cloud"
          >
            <img src="./logo.png" alt="Strix" className="w-10 h-8 object-cover" />
            <div className="text-base text-white font-medium tracking-tight">Strix</div>
          </a>
          <span className="ml-3 text-xs text-[#666]">Local results</span>
          {run && <LiveIndicator finished={run.finished} />}
        </div>
      </div>

      <div className="max-w-[88rem] mx-auto px-6 py-8 space-y-6">
        {/* Trust banner */}
        <div className="rounded-lg px-4 py-3 flex gap-3 items-start" style={{ border: "1px solid rgba(255,255,255,0.08)" }}>
          <ShieldCheck className="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-400" aria-hidden="true" />
          <p className="text-sm text-[#aaa] leading-relaxed">{TRUST_BANNER}</p>
        </div>

        {error && !run && (
          <div className="rounded-lg px-4 py-3 flex gap-3 items-start border border-red-500/30 bg-red-500/5">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-red-400" aria-hidden="true" />
            <p className="text-sm text-red-300">{error}</p>
          </div>
        )}

        {!run && !error && (
          <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-10 text-center">
            <div className="w-6 h-6 mx-auto mb-3 rounded-full border-2 border-[#333] border-t-white animate-spin" />
            <p className="text-sm text-[#888]">Loading run data…</p>
          </div>
        )}

        {run && counts && (
          <>
            <SummaryHeader summary={run.summary} />

            <UpsellRow />

            <div className="flex gap-5 border-b border-[#2a2a2a]">
              <TabButton active={view === "overview"} onClick={() => setView("overview")}>
                Overview
              </TabButton>
              <TabButton active={view === "issues"} onClick={() => setView("issues")}>
                Issues{run.vulnerabilities.length > 0 ? ` (${run.vulnerabilities.length})` : ""}
              </TabButton>
              {agentCount > 0 && (
                <TabButton active={view === "agents"} onClick={() => setView("agents")}>
                  Agents ({agentCount})
                </TabButton>
              )}
            </div>

            {view === "overview" ? (
              <OverviewTab
                summary={run.summary}
                counts={counts}
                total={run.vulnerabilities.length}
                reportMarkdown={run.reportMarkdown}
              />
            ) : view === "agents" && agentCount > 0 ? (
              <AgentsTab run={run} />
            ) : selected ? (
              <div className="space-y-4">
                <button
                  onClick={() => setSelectedId(null)}
                  className="cursor-pointer inline-flex items-center gap-1.5 text-sm text-[#888] hover:text-white transition-colors"
                >
                  <ArrowLeft className="w-4 h-4" /> Back to all findings
                </button>
                <VulnerabilityDetail vulnerability={selected} />
              </div>
            ) : (
              <FindingsList
                vulnerabilities={run.vulnerabilities}
                finished={run.finished}
                onSelect={(id) => setSelectedId(id)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function LiveIndicator({ finished }: { finished: boolean }) {
  if (finished) {
    return (
      <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-[#888]">
        <span className="w-1.5 h-1.5 rounded-full bg-[#555]" />
        Complete
      </span>
    );
  }
  return (
    <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-emerald-400">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
      </span>
      Live
    </span>
  );
}

function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null;
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function SummaryHeader({ summary }: { summary: ParsedRunSummary }) {
  const duration = formatDuration(summary.durationSeconds);
  return (
    <div>
      <h1 className="text-2xl font-semibold text-white">
        {summary.runName ?? summary.runId ?? "Scan results"}
      </h1>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[#888]">
        {summary.targets.length > 0 && (
          <span className="font-mono text-[#aaa]">{summary.targets.join(", ")}</span>
        )}
        {summary.scanMode && <Meta label={summary.scanMode} />}
        {duration && <Meta label={duration} />}
        {summary.status && <Meta label={summary.status} />}
      </div>
    </div>
  );
}

function Meta({ label }: { label: string }) {
  return (
    <>
      <span className="text-[#333]">·</span>
      <span className="capitalize">{label}</span>
    </>
  );
}

function FindingsList({
  vulnerabilities,
  finished,
  onSelect,
}: {
  vulnerabilities: Vulnerability[];
  finished: boolean;
  onSelect: (id: string) => void;
}) {
  const sorted = [...vulnerabilities].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
  );
  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-8 text-center text-sm text-[#888]">
        {finished ? "No findings in this run." : "No findings yet. The scan is still running…"}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {sorted.map((v) => (
        <button
          key={v.id}
          onClick={() => onSelect(v.id)}
          className="cursor-pointer w-full text-left rounded-lg border border-[#222] hover:border-[#444] bg-[rgba(255,255,255,0.02)] px-4 py-3 transition-colors flex items-center gap-3"
        >
          <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${getSeverityDot(v.severity)}`} aria-hidden="true" />
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-medium text-white truncate">{v.title}</span>
            {v.target && (
              <span className="block text-xs text-[#666] font-mono truncate">{v.target}</span>
            )}
          </span>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full border capitalize ${SEVERITY_COLORS[v.severity]}`}
          >
            {v.severity}
          </span>
        </button>
      ))}
    </div>
  );
}

/** Strip a single leading markdown heading (report sections embed their own). */
function stripLeadingHeading(md: string): string {
  return md.replace(/^\s*#{1,6}[ \t]+.*(?:\r?\n)+/, "").trimStart();
}

function dedupeHeadings(md: string): string {
  const out: string[] = [];
  let lastHeading: string | null = null;
  for (const line of md.split("\n")) {
    const m = line.match(/^#{1,6}\s+(.*)$/);
    if (m) {
      const norm = m[1].trim().toLowerCase();
      if (norm === lastHeading) continue;
      lastHeading = norm;
    } else if (line.trim() !== "") {
      lastHeading = null;
    }
    out.push(line);
  }
  return out.join("\n");
}

function OverviewTab({
  summary,
  counts,
  total,
  reportMarkdown,
}: {
  summary: ParsedRunSummary;
  counts: Record<VulnerabilitySeverity, number>;
  total: number;
  reportMarkdown: string | null;
}) {
  const sections = (
    [
      ["Executive Summary", summary.executiveSummary],
      ["Technical Analysis", summary.technicalAnalysis],
      ["Methodology", summary.methodology],
      ["Recommendations", summary.recommendations],
    ] as const
  )
    .filter(([, content]) => !!content)
    .map(([title, content]) => ({ title, content: stripLeadingHeading(content as string) }));

  return (
    <div className="space-y-6">
      {total > 0 && (
        <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-5">
          <IssueSeveritySummary findings={{ total, ...counts }} />
        </div>
      )}
      {sections.length > 0 ? (
        <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-5 space-y-8">
          {sections.map((s) => (
            <ContentSection key={s.title} title={s.title} content={s.content} />
          ))}
        </div>
      ) : reportMarkdown ? (
        <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-5">
          <ContentSection content={dedupeHeadings(reportMarkdown)} />
        </div>
      ) : (
        total === 0 && (
          <p className="text-sm text-[#888]">No summary available for this run yet.</p>
        )
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`cursor-pointer relative pb-2.5 text-sm font-semibold transition-colors ${
        active ? "text-white" : "text-[#666] hover:text-white"
      }`}
    >
      {children}
      {active && <span className="absolute bottom-0 inset-x-0 h-0.5 bg-white rounded-full" />}
    </button>
  );
}

const UPSELLS: { feature: string; title: string; desc: string; icon: React.ElementType }[] = [
  {
    feature: "cloud pentests",
    title: "Re-run in Strix Cloud",
    desc: "Run this scan on managed infra with more depth.",
    icon: Rocket,
  },
  {
    feature: "scheduled scans",
    title: "Schedule recurring scans",
    desc: "Continuously retest on a cadence you choose.",
    icon: CalendarClock,
  },
  {
    feature: "PR reviews",
    title: "PR security reviews",
    desc: "Catch vulnerabilities in every pull request.",
    icon: GitPullRequest,
  },
];

function UpsellRow() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {UPSELLS.map((u) => {
        const Icon = u.icon;
        return (
          <a
            key={u.title}
            href={SIGNUP_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackCta(u.feature)}
            className="cursor-pointer text-left rounded-xl border border-[#222] hover:border-[#444] bg-[rgba(255,255,255,0.02)] p-4 transition-colors group block"
          >
            <div className="flex items-center justify-between mb-2">
              <Icon className="w-4 h-4 text-[#888] group-hover:text-white transition-colors" />
              <Lock className="w-3.5 h-3.5 text-[#555]" aria-hidden="true" />
            </div>
            <p className="text-sm font-medium text-white">{u.title}</p>
            <p className="text-xs text-[#666] mt-0.5">{u.desc}</p>
          </a>
        );
      })}
    </div>
  );
}

function AgentsTab({ run }: { run: LoadedRun }) {
  const { agents, events } = run.transcript;
  const graphAgents = useMemo(() => buildGraphAgents(agents, events), [agents, events]);
  // Clicking a graph node opens the agent's transcript in a modal (matching the
  // cloud app); no node selected means no modal.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedAgent = selectedId ? (agents.find((a) => a.id === selectedId) ?? null) : null;

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#222] bg-[rgba(255,255,255,0.02)] p-5">
        <div className="flex items-center gap-2">
          <Waypoints className="w-4 h-4 text-[#888]" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-white">Agent graph</h2>
          <span className="text-xs text-[#666]">
            {agents.length} agent{agents.length === 1 ? "" : "s"}
          </span>
        </div>
        <p className="mt-1 mb-4 text-xs text-[#666]">
          Click an agent to open its full transcript.
        </p>
        <div className="h-[480px] rounded-lg border border-[#1a1a1a] overflow-hidden">
          <AgentGraph
            agents={graphAgents}
            selectedAgentId={selectedId}
            onSelectAgent={(id) => setSelectedId(id)}
            eventsLoaded
            eventsEmpty={graphAgents.size === 0}
            scanCompleted={run.finished}
          />
        </div>
      </div>

      {selectedAgent && (
        <AgentDetailModal
          agent={selectedAgent}
          events={events}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
