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

type PlatformStatus = {
  settings: {
    channel: string;
    status: string;
    is_active: boolean;
    phone_number_id: string | null;
    display_number: string | null;
    template_name: string | null;
    template_language: string | null;
    has_token: boolean;
  };
  bootstrap_phone: string;
};

export default function AdminPage() {
  const router = useRouter();
  const { accountId } = useWorkspace();
  const [me, setMe] = useState<Me | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [platform, setPlatform] = useState<PlatformStatus | null>(null);
  const [sender, setSender] = useState({
    phone_number_id: "",
    access_token: "",
    display_number: "",
    template_name: "",
    template_language: "en_US",
    test_to: "",
  });
  const [senderBusy, setSenderBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const meData = await api<Me>("/dashboard/me", { accountId });
      setMe(meData);
      if (!meData.is_superadmin) return;
      const [tenantData, auditData, platformData] = await Promise.all([
        api<{ items: Tenant[] }>("/admin/tenants"),
        api<{ items: AuditRow[] }>("/admin/audit"),
        api<PlatformStatus>("/admin/platform"),
      ]);
      setTenants(tenantData.items);
      setAudit(auditData.items);
      setPlatform(platformData);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveSender(event: React.FormEvent) {
    event.preventDefault();
    setSenderBusy(true);
    setError(null);
    try {
      await api("/admin/platform/whatsapp", {
        method: "PUT",
        body: {
          phone_number_id: sender.phone_number_id,
          access_token: sender.access_token,
          display_number: sender.display_number || null,
          template_name: sender.template_name || null,
          template_language: sender.template_language || "en_US",
        },
      });
      setSender((current) => ({ ...current, access_token: "" }));
      setError(null);
      await load();
    } catch (cause) {
      const err = cause as ApiError;
      setError(err.status === 400 ? "Meta rejected that token / phone number id." : err.detail);
    } finally {
      setSenderBusy(false);
    }
  }

  async function testSender() {
    setSenderBusy(true);
    setError(null);
    try {
      await api("/admin/platform/test", { method: "POST", body: { to: sender.test_to } });
      setError(null);
      alert("Test message sent.");
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setSenderBusy(false);
    }
  }

  async function disableSender() {
    if (!window.confirm("Disable the platform sender? Login OTPs will stop being delivered.")) return;
    try {
      await api("/admin/platform/whatsapp", { method: "DELETE" });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

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

      <form className="card" onSubmit={saveSender} style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div className="card-title">Platform WhatsApp sender</div>
            <div className="card-sub">
              One number sends every login OTP. Separate from tenant agent numbers.
            </div>
          </div>
          {platform?.settings.is_active ? (
            <Pill tone="ok">active{platform.settings.display_number ? ` · ${platform.settings.display_number}` : ""}</Pill>
          ) : (
            <Pill tone="warn">not configured</Pill>
          )}
        </div>

        <div className="muted" style={{ marginTop: 8 }}>
          Requires a Meta WABA phone number id + access token. Use an approved authentication template
          for OTPs outside the 24-hour window. Until this is active only the bootstrap phone
          ({platform?.bootstrap_phone ?? "—"}) can log in.
        </div>

        <div className="two-col" style={{ marginTop: 12 }}>
          <label className="field">
            <span>Phone number id</span>
            <input
              value={sender.phone_number_id}
              onChange={(event) => setSender({ ...sender, phone_number_id: event.target.value })}
              placeholder="712594308615206"
            />
          </label>
          <label className="field">
            <span>Access token {platform?.settings.has_token ? "(stored — replace only)" : ""}</span>
            <input
              type="password"
              autoComplete="off"
              value={sender.access_token}
              onChange={(event) => setSender({ ...sender, access_token: event.target.value })}
              placeholder={platform?.settings.has_token ? "••••••••" : "EAAB…"}
            />
          </label>
          <label className="field">
            <span>Display number (optional)</span>
            <input
              value={sender.display_number}
              onChange={(event) => setSender({ ...sender, display_number: event.target.value })}
              placeholder="+91 99999 00001"
            />
          </label>
          <label className="field">
            <span>OTP template (optional)</span>
            <input
              value={sender.template_name}
              onChange={(event) => setSender({ ...sender, template_name: event.target.value })}
              placeholder="wasignal_otp"
            />
          </label>
          <label className="field">
            <span>Template language</span>
            <input
              value={sender.template_language}
              onChange={(event) => setSender({ ...sender, template_language: event.target.value })}
              placeholder="en_US"
            />
          </label>
          <label className="field">
            <span>Send test to</span>
            <input
              value={sender.test_to}
              onChange={(event) => setSender({ ...sender, test_to: event.target.value })}
              placeholder="919999000001"
            />
          </label>
        </div>

        <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
          {platform?.settings.is_active ? (
            <button type="button" className="btn ghost sm" onClick={disableSender}>
              Disable
            </button>
          ) : null}
          <button
            type="button"
            className="btn ghost sm"
            onClick={testSender}
            disabled={senderBusy || !sender.test_to}
          >
            Send test
          </button>
          <button className="btn sm" type="submit" disabled={senderBusy}>
            {senderBusy ? "Saving…" : platform?.settings.is_active ? "Replace credentials" : "Activate sender"}
          </button>
        </div>
      </form>

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
