"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Mail, Plus, ShieldCheck, Trash2, UserPlus } from "lucide-react";

import { ApiError, TeamPayload, api } from "@/lib/api";
import { EmptyState, Field, Modal, PageHeader, Pill } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

type MyInvite = { token: string; org_id: number; org_name: string; role: string; expires_at: number };

const ROLES = ["admin", "manager", "member", "viewer"];

export default function TeamPage() {
  const { accountId } = useWorkspace();
  const [team, setTeam] = useState<TeamPayload | null>(null);
  const [invites, setInvites] = useState<MyInvite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [form, setForm] = useState({ phone: "", role: "member" });
  const [createdLink, setCreatedLink] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [teamData, inviteData] = await Promise.all([
        api<TeamPayload>("/dashboard/team", { accountId }),
        api<{ items: MyInvite[] }>("/dashboard/invitations", { accountId }),
      ]);
      setTeam(teamData);
      setInvites(inviteData.items);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  const canManage = team?.role === "owner" || team?.role === "admin";

  async function invite(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId) return;
    setError(null);
    try {
      const invitation = await api<{ token: string }>("/dashboard/organization/invitations", {
        method: "POST",
        accountId,
        body: form,
      });
      const link = `${window.location.origin}/dashboard/team?invite=${invitation.token}`;
      setCreatedLink(link);
      setInviting(false);
      setForm({ phone: "", role: "member" });
      await load();
    } catch (cause) {
      const err = cause as ApiError;
      setError(
        err.status === 402
          ? "No seats left on this plan. Upgrade in Billing or remove a member first."
          : err.status === 409
            ? "That person is already a member or already invited."
            : err.detail,
      );
    }
  }

  async function changeRole(pid: number, role: string) {
    if (!accountId) return;
    try {
      await api(`/dashboard/organization/members/${pid}`, { method: "PATCH", accountId, body: { role } });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function removeMember(pid: number) {
    if (!accountId) return;
    try {
      await api(`/dashboard/organization/members/${pid}`, { method: "DELETE", accountId });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function revoke(id: number) {
    if (!accountId) return;
    try {
      await api(`/dashboard/organization/invitations/${id}`, { method: "DELETE", accountId });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function answerInvite(token: string, accept: boolean) {
    if (!accountId) return;
    try {
      await api(`/dashboard/invitations/${token}/${accept ? "accept" : "decline"}`, {
        method: "POST",
        accountId,
      });
      setNotice(accept ? "Invitation accepted — switch organization to use it." : "Invitation declined.");
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice("Invite link copied.");
    } catch {
      setNotice(text);
    }
  }

  return (
    <>
      <PageHeader
        title="Team"
        subtitle="Who can see this organization, and what they can do."
        action={
          <button className="btn" onClick={() => setInviting(true)} disabled={!canManage}>
            <UserPlus /> Invite
          </button>
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {notice ? (
        <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)", marginBottom: 14 }}>
          {notice}
        </div>
      ) : null}

      {invites.length ? (
        <div className="card" style={{ background: "#fffdf4", borderColor: "var(--warn-line)", marginBottom: 14 }}>
          <div className="card-title">Invitations for you</div>
          {invites.map((invite) => (
            <div
              key={invite.token}
              style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, flexWrap: "wrap" }}
            >
              <span>
                <strong>{invite.org_name}</strong> · {invite.role} · expires {dateTime(invite.expires_at)}
              </span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button className="btn sm" onClick={() => answerInvite(invite.token, true)}>
                  Accept
                </button>
                <button className="btn ghost sm" onClick={() => answerInvite(invite.token, false)}>
                  Decline
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div className="card-title">{team?.organization.name ?? "Organization"}</div>
            <div className="card-sub">
              {team ? (
                <>
                  {team.plan} plan · {team.seats.used + team.seats.pending} of {team.seats.limit} seats
                </>
              ) : (
                "Loading…"
              )}
            </div>
          </div>
          {team ? <Pill tone="ok">{team.role}</Pill> : null}
        </div>

        {team ? (
          <table className="table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Role</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {team.members.map((member) => (
                <tr key={member.pid}>
                  <td>
                    <div className="item-title">
                      {member.name}
                      {member.is_owner ? <Pill tone="ok">owner</Pill> : null}
                    </div>
                  </td>
                  <td className="muted">{member.phone}</td>
                  <td>
                    {canManage && !member.is_owner ? (
                      <select
                        value={member.role}
                        onChange={(event) => changeRole(member.pid, event.target.value)}
                        style={{ width: 130 }}
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Pill>{member.role}</Pill>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {canManage && !member.is_owner ? (
                      <button className="btn ghost sm" onClick={() => removeMember(member.pid)}>
                        <Trash2 />
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>

      <div className="card">
        <div className="card-title">Pending invitations</div>
        <div className="card-sub">They can accept once they have a Wasignal account with that number.</div>

        {team?.invitations.length ? (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Phone</th>
                <th>Role</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {team.invitations.map((invite) => (
                <tr key={invite.id}>
                  <td>{invite.phone}</td>
                  <td>
                    <Pill>{invite.role}</Pill>
                  </td>
                  <td className="muted">{dateTime(invite.expires_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    <span style={{ display: "inline-flex", gap: 8 }}>
                      <button
                        className="btn ghost sm"
                        onClick={() =>
                          copy(`${window.location.origin}/dashboard/team?invite=${invite.token}`)
                        }
                      >
                        <Copy /> Link
                      </button>
                      {canManage ? (
                        <button className="btn ghost sm" onClick={() => revoke(invite.id)}>
                          <Trash2 />
                        </button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ marginTop: 10 }}>
            <EmptyState
              title="No pending invitations"
              detail="Invite a teammate when their number can receive the OTP."
              action={
                <span className="muted">
                  <ShieldCheck style={{ width: 13, height: 13, verticalAlign: -2 }} /> Roles: admin, manager, member,
                  viewer
                </span>
              }
            />
          </div>
        )}

        <div className="divider" />
        <div className="row" style={{ gap: 8, marginTop: 6 }}>
          <Mail style={{ width: 15, height: 15, color: "var(--muted)" }} />
          <span className="muted">Invitations expire after 7 days and are bound to the phone number.</span>
        </div>
      </div>

      {createdLink ? (
        <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)" }}>
          <div className="card-title">Invite ready</div>
          <div className="row" style={{ gap: 8, marginTop: 6 }}>
            <code style={{ overflowWrap: "anywhere" }}>{createdLink}</code>
            <button className="btn ghost sm" onClick={() => copy(createdLink)}>
              <Copy /> Copy
            </button>
            <button className="btn ghost sm" onClick={() => setCreatedLink(null)}>
              Done
            </button>
          </div>
        </div>
      ) : null}

      {inviting ? (
        <Modal title="Invite a teammate" onClose={() => setInviting(false)}>
          <form className="form" onSubmit={invite}>
            <Field label="WhatsApp number">
              <input
                required
                value={form.phone}
                onChange={(event) => setForm({ ...form, phone: event.target.value })}
                placeholder="98765 43210"
                inputMode="tel"
              />
            </Field>
            <Field label="Role">
              <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </Field>
            <p className="muted">
              admin: billing + team · manager: agents, knowledge, channels · member: chat and send · viewer:
              read-only.
            </p>
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setInviting(false)}>
                Cancel
              </button>
              <button className="btn" type="submit">
                <Plus /> Create invite
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </>
  );
}
