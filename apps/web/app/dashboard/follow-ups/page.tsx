"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock, Plus } from "lucide-react";

import { Agent, ApiError, api } from "@/lib/api";
import { Field, Modal, PageHeader, Pill } from "@/components/ui";
import { timeAgo } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

type Rule = { id?: string; message: string; message_mode: "generated" | "verbatim"; delay_seconds: number };
type Window = { timezone?: string; days?: number[]; start?: string; end?: string } | null;
type Rules = { enabled: boolean; rules: Rule[]; send_window: Window };
type Run = { id: number; rule_key: string; room_id: number; due_at: number; sent_at: number | null; status: string };

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function FollowUpsPage() {
  const { accountId } = useWorkspace();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) return;
    api<{ items: Agent[] }>("/dashboard/agents", { accountId })
      .then((data) => setAgents(data.items))
      .catch((cause) => setError((cause as ApiError).detail));
  }, [accountId]);

  return (
    <>
      <PageHeader
        title="Follow-ups"
        subtitle="Nudge the leads who went quiet — in context, inside business hours, capped."
      />
      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {agents.map((agent) => (
        <FollowUpCard key={agent.id} agent={agent} accountId={accountId} />
      ))}
    </>
  );
}

function FollowUpCard({ agent, accountId }: { agent: Agent; accountId: number | null }) {
  const [rules, setRules] = useState<Rules | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ message: "", hours: "12", mode: "generated" as Rule["message_mode"] });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [rulesData, runsData] = await Promise.all([
        api<Rules>(`/dashboard/agents/${agent.id}/follow-up-rules`, { accountId }),
        api<{ items: Run[] }>(`/dashboard/agents/${agent.id}/follow-up-runs`, { accountId }),
      ]);
      setRules(rulesData);
      setRuns(runsData.items.slice(0, 5));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId, agent.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(next: Rules) {
    if (!accountId) return;
    try {
      const saved = await api<Rules>(`/dashboard/agents/${agent.id}/follow-up-rules`, {
        method: "PUT",
        accountId,
        body: {
          enabled: next.enabled,
          rules: next.rules,
          send_window: next.send_window ?? undefined,
        },
      });
      setRules(saved);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function addRule(event: React.FormEvent) {
    event.preventDefault();
    if (!rules) return;
    const delay = Math.max(60, Math.round(Number(form.hours) * 3600));
    const next: Rules = {
      ...rules,
      enabled: true,
      rules: [
        ...rules.rules,
        {
          id: `r${rules.rules.length + 1}`,
          message: form.message,
          message_mode: form.mode,
          delay_seconds: delay,
        },
      ],
    };
    await save(next);
    setEditing(false);
    setForm({ message: "", hours: "12", mode: "generated" });
  }

  const window = rules?.send_window ?? { timezone: "Asia/Kolkata", days: [0, 1, 2, 3, 4, 5], start: "09:00", end: "21:00" };

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <div className="item-title" style={{ fontSize: 14.5 }}>
            {agent.name}
            <Pill tone={rules?.enabled ? "ok" : undefined}>{rules?.enabled ? "on" : "off"}</Pill>
          </div>
          <div className="row-sub">
            {rules ? `${rules.rules.length} rule(s)` : "loading…"}
            {rules?.send_window ? ` · ${rules.send_window.start}–${rules.send_window.end}` : ""}
          </div>
        </div>
        <div className="row-action">
          <button className="btn ghost sm" onClick={() => setEditing(true)}>
            <Plus /> Rule
          </button>
          <button
            className="btn ghost sm"
            onClick={() => rules && save({ ...rules, enabled: !rules.enabled })}
            disabled={!rules}
          >
            {rules?.enabled ? "Turn off" : "Turn on"}
          </button>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {rules?.rules.length ? (
        <table className="table" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>After</th>
              <th>Message</th>
              <th>Mode</th>
            </tr>
          </thead>
          <tbody>
            {rules.rules.map((rule, index) => (
              <tr key={rule.id ?? index}>
                <td>{Math.round(rule.delay_seconds / 3600)}h</td>
                <td style={{ maxWidth: 460 }}>{rule.message}</td>
                <td>
                  <Pill>{rule.message_mode}</Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <div className="divider" />

      <div className="two-col">
        <div className="field">
          <span>Send window</span>
          <div className="row" style={{ gap: 8 }}>
            <input
              type="time"
              value={window.start ?? "09:00"}
              onChange={(event) => rules && save({ ...rules, send_window: { ...window, start: event.target.value } })}
              style={{ width: 110 }}
            />
            <span className="muted">to</span>
            <input
              type="time"
              value={window.end ?? "21:00"}
              onChange={(event) => rules && save({ ...rules, send_window: { ...window, end: event.target.value } })}
              style={{ width: 110 }}
            />
            <span className="muted">{window.timezone ?? "Asia/Kolkata"}</span>
          </div>
        </div>
        <div className="field">
          <span>Days</span>
          <div className="chips">
            {DAYS.map((day, index) => {
              const on = (window.days ?? []).includes(index);
              return (
                <button
                  key={day}
                  className={`chip ${on ? "on" : ""}`}
                  onClick={() => {
                    if (!rules) return;
                    const days = new Set(window.days ?? []);
                    if (on) days.delete(index);
                    else days.add(index);
                    save({ ...rules, send_window: { ...window, days: [...days].sort() } });
                  }}
                  type="button"
                >
                  {day}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="divider" />
      <div className="card-sub" style={{ marginBottom: 6 }}>
        Recent follow-up runs
      </div>
      {runs.length ? (
        <table className="table">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Status</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>{run.rule_key}</td>
                <td>
                  <Pill tone={run.status === "sent" ? "ok" : "warn"}>{run.status}</Pill>
                </td>
                <td className="muted">{timeAgo(run.sent_at ?? run.due_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="muted">No follow-ups have fired yet.</div>
      )}

      {editing ? (
        <Modal title={`Add follow-up — ${agent.name}`} onClose={() => setEditing(false)}>
          <form className="form" onSubmit={addRule}>
            <Field label="Instruction or message">
              <textarea
                required
                rows={3}
                value={form.message}
                onChange={(event) => setForm({ ...form, message: event.target.value })}
                placeholder="Nudge them about what they asked, mention stock, keep it short."
              />
            </Field>
            <div className="two-col">
              <Field label="After (hours of silence)">
                <input type="number" min={1} value={form.hours} onChange={(event) => setForm({ ...form, hours: event.target.value })} />
              </Field>
              <Field label="Mode">
                <select value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value as Rule["message_mode"] })}>
                  <option value="generated">Written by the agent</option>
                  <option value="verbatim">Send exactly this</option>
                </select>
              </Field>
            </div>
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setEditing(false)}>
                Cancel
              </button>
              <button className="btn" type="submit">
                <Clock /> Add rule
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
