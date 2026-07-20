import React from "react";
import {
  FileText,
  Bug,
  Waypoints,
  History,
  Mail,
  GitPullRequest,
  Search,
  Layers,
  Globe,
  Puzzle,
  Users,
  LayoutDashboard,
  AlertTriangle,
  MessageSquare,
  Network,
  Database,
  ArrowUpRight,
  LogOut,
  ShieldCheck,
} from "lucide-react";
import { SIGNUP_URL, trackCta } from "@/lib/cta";
import { ProNavItem, type ProItem } from "@/components/ProCta";
import type { View } from "@/App";

/**
 * Persistent left rail. Mirrors the cloud app's nav: real in-page content
 * ("This run"), local email-gated features ("Your runs"), and org-oriented
 * Pro link-outs ("Platform"). Matches App.tsx's dark palette.
 */

// Org-signal items lead the list (PR Reviews, Repositories, Domains,
// Integrations, Members), then the rest of the platform surface.
const PLATFORM_ITEMS: ProItem[] = [
  { title: "PR Reviews", desc: "Pentest every pull request your team opens.", slug: "pr_reviews", icon: GitPullRequest },
  { title: "Repositories", desc: "Connect your org's repositories and domains.", slug: "repositories", icon: Layers },
  { title: "Domains", desc: "Connect your org's repositories and domains.", slug: "domains", icon: Globe },
  { title: "Integrations", desc: "Two-way sync findings to Jira, Linear, and Slack.", slug: "integrations", icon: Puzzle },
  { title: "Members", desc: "Invite your team and set roles.", slug: "members", icon: Users },
  { title: "Pentests", desc: "Launch deeper pentests on managed infra.", slug: "pentests", icon: Search },
  { title: "Dashboard", desc: "See every project and finding in one place.", slug: "dashboard", icon: LayoutDashboard },
  { title: "Issues", desc: "Track and triage findings across your org.", slug: "platform_issues", icon: AlertTriangle },
  { title: "Chat", desc: "Ask the agents about any finding.", slug: "chat", icon: MessageSquare },
  { title: "Networks", desc: "Map and monitor your network exposure.", slug: "networks", icon: Network },
  { title: "Knowledge", desc: "Give agents context about your systems.", slug: "knowledge", icon: Database },
];

interface SidebarProps {
  view: View;
  onSelectView: (view: View) => void;
  issuesCount: number;
  agentCount: number;
  runCount: number;
  verified: boolean;
  email: string | null;
  onOpenEmail: () => void;
  onOpenHistory: () => void;
  onForget: () => void;
}

export default function Sidebar({
  view,
  onSelectView,
  issuesCount,
  agentCount,
  runCount,
  verified,
  email,
  onOpenEmail,
  onOpenHistory,
  onForget,
}: SidebarProps) {
  return (
    <aside className="hidden w-60 flex-shrink-0 border-r border-[#222] lg:block">
      <div className="sticky top-0 flex h-screen flex-col overflow-y-auto px-3 py-4">
        {/* Header: wordmark + Start free + signed-in chip */}
        <div className="px-1.5">
          <a
            href="https://app.strix.ai"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackCta("logo")}
            className="flex items-center gap-1.5 opacity-90 transition-opacity hover:opacity-100"
            title="Open Strix Cloud"
          >
            <img src="./logo.png" alt="Strix" className="h-8 w-10 object-cover" />
            <span className="text-base font-medium tracking-tight text-white">Strix</span>
          </a>
          <a
            href={SIGNUP_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackCta("sidebar_start_free")}
            className="mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-semibold text-black transition-opacity hover:opacity-90"
          >
            Start free
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
          {verified && email && (
            <div
              className="mt-2.5 flex items-center gap-2 rounded-lg px-2.5 py-2"
              style={{ border: "1px solid #222", background: "rgba(255,255,255,0.02)" }}
            >
              <ShieldCheck className="h-3.5 w-3.5 flex-shrink-0 text-emerald-400" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] text-[#666]">Signed in as</p>
                <p className="truncate text-xs text-[#aaa]" title={email}>{email}</p>
              </div>
              <button
                onClick={onForget}
                title="Forget this email on this machine"
                className="flex-shrink-0 cursor-pointer text-[#666] transition-colors hover:text-white"
                aria-label="Forget"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* This run */}
        <Section label="This run">
          <NavItem
            icon={FileText}
            label="Overview"
            active={view === "overview"}
            onClick={() => onSelectView("overview")}
          />
          <NavItem
            icon={Bug}
            label="Issues"
            count={issuesCount > 0 ? issuesCount : undefined}
            active={view === "issues"}
            onClick={() => onSelectView("issues")}
          />
          {agentCount > 0 && (
            <NavItem
              icon={Waypoints}
              label="Agents"
              count={agentCount}
              active={view === "agents"}
              onClick={() => onSelectView("agents")}
            />
          )}
        </Section>

        {/* Your runs (local, unlock with email) */}
        <Section label="Your runs">
          <NavItem
            icon={History}
            label="Past runs"
            count={runCount > 0 ? runCount : undefined}
            active={view === "history"}
            onClick={onOpenHistory}
          />
          <NavItem icon={Mail} label="Email report" onClick={onOpenEmail} />
        </Section>

        {/* Platform (Pro link-outs) */}
        <div className="mt-6">
          <p className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-[#555]">
            Platform
          </p>
          <p className="px-2.5 pb-2 text-[11px] leading-snug text-[#666]">
            Get the most out of Strix for your team.
          </p>
          <div className="space-y-0.5">
            {PLATFORM_ITEMS.map((item) => (
              <ProNavItem key={item.slug} item={item} />
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-6">
      <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#555]">
        {label}
      </p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function NavItem({
  icon: Icon,
  label,
  count,
  active,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  count?: number;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors ${
        active
          ? "text-white"
          : "text-[#888] hover:bg-[rgba(255,255,255,0.06)] hover:text-white"
      }`}
      style={active ? { background: "rgba(255,255,255,0.12)" } : undefined}
    >
      <Icon className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
      <span className="flex-1 text-left">{label}</span>
      {count != null && <span className="text-xs text-[#666] tabular-nums">{count}</span>}
    </button>
  );
}
