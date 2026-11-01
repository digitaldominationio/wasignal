"use client";

import { useEffect, useMemo, useState } from "react";

import { Agent, ApiError, api } from "@/lib/api";
import { EmptyState, PageHeader, Pill } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

type Run = {
  id: number;
  agent_id: number;
  status: string;
  trigger: string;
  stage: string;
  reason: string | null;
  reply: string;
  iterations: number;
  tokens: number;
  started_at: number;
  finished_at: number | null;
};

const TONE: Record<string, "ok" | "warn" | "bad" | undefined> = {
  ok: "ok",
  handover: "warn",
  limit: "warn",
  error: "bad",
  read_only: undefined,
};

export default function ActivityPage() {
  const { accountId } = useWorkspace();
  const [runs, setRuns] = useState<Run[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) return;
    Promise.all([
      api<{ items: Run[] }>("/dashboard/runs?limit=100", { accountId }),
      api<{ items: Agent[] }>("/dashboard/agents", { accountId }),
    ])
      .then(([runData, agentData]) => {
        setRuns(runData.items);
        setAgents(agentData.items);
      })
      .catch((cause) => setError((cause as ApiError).detail));
  }, [accountId]);

  const filtered = useMemo(
    () =>
      runs.filter(
        (run) =>
          (agentFilter === "all" || run.agent_id === Number(agentFilter)) &&
          (statusFilter === "all" || run.status === statusFilter),
      ),
    [runs, agentFilter, statusFilter],
  );

  return (
    <>
      <PageHeader title="Activity" subtitle="Every agent turn: what started it, what it did, and how it ended." />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      <div className="card">
        <div className="row" style={{ gap: 10, marginBottom: 10 }}>
          <select value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} style={{ width: 220 }}>
            <option value="all">All automations</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} style={{ width: 160 }}>
            <option value="all">Any status</option>
            {["ok", "handover", "read_only", "limit", "error"].map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
          <span className="muted" style={{ marginLeft: "auto" }}>
            {filtered.length} run(s)
          </span>
        </div>

        {filtered.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Automation</th>
                <th>Trigger</th>
                <th>Reply</th>
                <th>Steps</th>
                <th>Tokens</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Pill tone={TONE[run.status]}>{run.status}</Pill>
                  </td>
                  <td className="muted">{agents.find((agent) => agent.id === run.agent_id)?.name ?? run.agent_id}</td>
                  <td className="muted">{run.trigger}</td>
                  <td style={{ maxWidth: 340 }}>
                    {run.reply ? run.reply.slice(0, 160) : <span className="muted">{run.reason ?? "no reply"}</span>}
                  </td>
                  <td>{run.iterations}</td>
                  <td>{run.tokens}</td>
                  <td className="muted">{dateTime(run.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No runs match" detail="Send a message from the Assistant, or relax the filters." />
        )}
      </div>
    </>
  );
}
