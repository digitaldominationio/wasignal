"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  CalendarClock,
  CreditCard,
  EyeOff,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  MessageSquare,
  Plug,
  Settings,
  Sparkles,
  Tags,
  TriangleAlert,
  Users,
  Workflow,
} from "lucide-react";

import { api, clearToken } from "@/lib/api";
import { initials } from "@/lib/format";
import { WorkspaceProvider, useWorkspace } from "@/lib/workspace";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/automations", label: "Automations", icon: Workflow },
  { href: "/dashboard/assistant", label: "Assistant", icon: MessageSquare },
  { href: "/dashboard/scheduled", label: "Scheduled Messages", icon: CalendarClock },
  { href: "/dashboard/follow-ups", label: "Follow-ups", icon: Tags },
  { href: "/dashboard/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/dashboard/connections", label: "Connections", icon: Plug },
  { href: "/dashboard/excluded", label: "Excluded Chats", icon: EyeOff },
  { href: "/dashboard/activity", label: "Activity", icon: Activity },
  { href: "/dashboard/insights", label: "Insights", icon: BarChart3 },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
  { href: "/dashboard/team", label: "Team", icon: Users },
  { href: "/dashboard/billing", label: "Billing", icon: CreditCard },
];

type ConnectionState = { connected: boolean; detail?: string };
type OverviewStats = { messages_today: number };
type Quota = { plan: string; messages: { used: number; limit: number } };

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <Shell>{children}</Shell>
    </WorkspaceProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { accountId, account, partner, loading, error } = useWorkspace();
  const pathname = usePathname();
  const router = useRouter();
  const [whatsapp, setWhatsapp] = useState<ConnectionState | null>(null);
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [quota, setQuota] = useState<Quota | null>(null);

  const refreshShell = useCallback(async () => {
    if (!accountId) return;
    try {
      const connections = await api<{ whatsapp: ConnectionState }>("/dashboard/connections", { accountId });
      setWhatsapp(connections.whatsapp);
      const overview = await api<{ stats: OverviewStats }>("/dashboard/overview", { accountId });
      setStats(overview.stats);
      const quotaData = await api<Quota>("/dashboard/quota", { accountId });
      setQuota(quotaData);
    } catch {
      /* the page itself will surface errors */
    }
  }, [accountId]);

  useEffect(() => {
    void refreshShell();
  }, [refreshShell, pathname]);

  async function signOut() {
    try {
      await api("/dashboard/auth/logout", { method: "POST" });
    } finally {
      clearToken();
      router.replace("/login");
    }
  }

  const usedToday = stats?.messages_today ?? 0;
  const quotaLimit = quota?.messages.limit ?? 500;
  const quotaPercent = Math.min(100, Math.round((usedToday / Math.max(1, quotaLimit)) * 100));

  return (
    <div className="app">
      <aside className="sidebar">
        <Link href="/dashboard" className="brand">
          <span className="brand-mark">W</span>
          wasignal
        </Link>

        <nav className="nav">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = item.href === "/dashboard" ? pathname === item.href : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={`nav-item ${active ? "active" : ""}`}>
                <Icon />
                {item.label}
                {item.href === "/dashboard/connections" && whatsapp && !whatsapp.connected ? (
                  <span className="nav-dot" aria-label="Action needed" />
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="nav-spacer" />

        <div className="sidebar-foot">
          <Link href="/dashboard/assistant" className="promo">
            <MessageCircle />
            <span>Message your assistant</span>
          </Link>

          <div className="quota">
            <div className="quota-head">
              <span>Messages today</span>
              <span>
                {usedToday} / {quotaLimit}
              </span>
            </div>
            <div className="quota-bar">
              <span style={{ width: `${quotaPercent}%` }} />
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              {quota ? `${quota.plan} plan · ` : ""}resets monthly
            </div>
          </div>

          <div className="profile">
            <span className="avatar">{initials(partner?.name)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="profile-name">{partner?.name ?? "—"}</div>
              <div className="profile-meta">
                {account?.wa_number || "No number linked"} · PID {partner?.pid ?? "—"}
              </div>
            </div>
            <button className="btn ghost sm" onClick={signOut} title="Sign out" style={{ marginLeft: "auto" }}>
              <LogOut />
            </button>
          </div>
        </div>
      </aside>

      <main className="main">
        {whatsapp && !whatsapp.connected ? (
          <div className="banner">
            <TriangleAlert />
            <span>
              <strong>WhatsApp isn&apos;t connected.</strong> Your automations and scheduled messages won&apos;t run
              until you link your account.
            </span>
            <Link href="/dashboard/connections" className="btn sm">
              Connect now
            </Link>
          </div>
        ) : null}

        <div className="content">
          {error ? <div className="card" style={{ borderColor: "#f0cfcc" }}>{error}</div> : null}
          {loading ? <div className="muted">Loading workspace…</div> : children}
        </div>
      </main>
    </div>
  );
}
