"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ShieldCheck, UserCog } from "lucide-react";

import { ApiError, api, getStoredToken, storeToken } from "@/lib/api";
import { EmptyState, PageHeader, Pill } from "@/components/ui";
import { dateTime, timeAgo } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

const ADMIN_TOKEN_KEY = "ws_admin_token";

type Tenant = {
  id: number;
  name: string;
  slug: string | null;
  owner: { pid: number; name: string; phone: string };
  plan: string;
  status: string;
  numbers: number;
  agents: number;
  members: number;
  messages_tokens: number;
  last_activity: number;
  created_at: number;
};

type AuditRow = {
  id: number;
  actor_pid: number;
  org_id: number | null;
  action: string;
  detail: Record<string, unknown>;
  created_at: number;
};

type Me = { is_superadmin: boolean; impersonating: boolean; pid: number };

export default function AdminPage() {
  const router = useRouter();
  const { accountId } = useWorkspace();
  const [me, setMe] = useState<Me | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const meData = await api<Me>("/dashboard/me", { accountId });
      setMe(meData);
      if (!meData.is_superadmin) return;
      const [tenantData, auditData] = await Promise.all([
        api<{ items: Tenant[] }>("/admin/tenants"),
        api<{ items: AuditRow[] }>("/admin/audit"),
      ]);
      setTenants(tenantData.items);
      setAudit(auditData.items);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function impersonate(orgId: number) {
    setBusy(orgId);
    setError(null);
    try {
      const current = getStoredToken();
      const result = await api<{ access_token: string; org: { id: number; name: string } }>(
        `/admin/tenants/${orgId}/impersonate`,
        { method: "POST" },
      );
      if (current) window.localStorage.setItem(ADMIN_TOKEN_KEY, current);
      storeToken(result.access_token);
      window.localStorage.setItem("ws_impersonating", result.org.name);
      router.push("/dashboard");
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(null);
    }
  }

  if (me && !me.is_superadmin) {
    return (
      <>
        <PageHeader title="Platform admin" subtitle="Tenant troubleshooting and impersonation." />
        <EmptyState title="Superadmin access required" detail="This area is limited to platform administrators." />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Platform admin"
        subtitle="Every workspace, its usage, and a way to step into it when a tenant needs help."
        action={<Pill tone="ok">{tenants.length} tenants</Pill>}
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      <div className="card">
        <div className="card-title">Tenants</div>
        <div className="card-sub">
          Impersonation opens the tenant&apos;s workspace with their data. Writes are allowed and audit-logged.
        </div>

        {tenants.length ? (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Workspace</th>
                <th>Owner</th>
                <th>Plan</th>
                <th>Numbers</th>
                <th>Agents</th>
                <th>Last activity</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{tenant.name}</div>
                    <div className="row-sub">org #{tenant.id}</div>
                  </td>
                  <td>
                    <div>{tenant.owner.name || "—"}</div>
                    <div className="row-sub">{tenant.owner.phone}</div>
                  </td>
                  <td>
                    <Pill tone={tenant.status === "active" ? "ok" : "warn"}>{tenant.plan}</Pill>
                  </td>
                  <td>{tenant.numbers}</td>
                  <td>{tenant.agents}</td>
                  <td className="muted">{tenant.last_activity ? timeAgo(tenant.last_activity) : "never"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn sm" onClick={() => impersonate(tenant.id)} disabled={busy === tenant.id}>
                      <UserCog /> {busy === tenant.id ? "Opening…" : "Impersonate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ marginTop: 12 }}>
            <EmptyState title="No tenants yet" />
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Admin audit</div>
        <div className="card-sub">Impersonation starts/stops and any write performed while impersonating.</div>
        {audit.length ? (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Action</th>
                <th>Org</th>
                <th>Detail</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {audit.slice(0, 25).map((row) => (
                <tr key={row.id}>
                  <td>
                    <Pill tone={row.action === "impersonate_start" ? "warn" : row.action === "impersonate_stop" ? "ok" : undefined}>
                      {row.action}
                    </Pill>
                  </td>
                  <td className="muted">{row.org_id ?? "—"}</td>
                  <td className="muted" style={{ maxWidth: 420 }}>
                    {Object.entries(row.detail || {})
                      .map(([key, value]) => `${key}: ${String(value)}`)
                      .join(" · ") || "—"}
                  </td>
                  <td className="muted">{dateTime(row.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="muted" style={{ marginTop: 10 }}>
            No admin actions yet.
          </div>
        )}
      </div>

      <div className="card" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <ShieldCheck style={{ width: 16, height: 16, color: "var(--ok)" }} />
        <div className="muted" style={{ flex: 1 }}>
          Superadmins are bootstrapped with <code>WASIGNAL_SUPERADMIN_PHONES</code> or seeded for the demo tenant.
        </div>
        <button className="btn ghost sm" onClick={() => router.push("/dashboard")}>
          Dashboard <ArrowRight />
        </button>
      </div>
    </>
  );
}
