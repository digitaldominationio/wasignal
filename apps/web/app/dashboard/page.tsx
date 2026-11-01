"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, MessageSquare, Sparkles } from "lucide-react";

import { PageHeader, Pill, Stat } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { initials, timeAgo } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

type Overview = {
  stats: {
    active_agents: number;
    agents: number;
    rooms: number;
    messages_today: number;
    runs_today: number;
    followups_sent: number;
    queued: number;
  };
  attention: { id: string; title: string; detail: string; href: string; cta: string }[];
  recent_runs: {
    id: number;
    status: string;
    trigger: string;
    reply: string;
    iterations: number;
    tokens: number;
    started_at: number;
  }[];
  rooms: { id: number; display_name: string; kind: string; last_activity_at: number }[];
};

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | undefined> = {
  ok: "ok",
  read_only: undefined,
  handover: "warn",
  limit: "warn",
  error: "bad",
  running: undefined,
};

export default function OverviewPage() {
  const { accountId } = useWorkspace();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) return;
    api<Overview>("/dashboard/overview", { accountId })
      .then(setData)
      .catch((cause) => setError((cause as ApiError).detail));
  }, [accountId]);

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Everything your agents did today, and what needs your attention."
        action={
          <Link href="/dashboard/automations" className="btn">
            <Sparkles /> New automation
          </Link>
        }
      />

      {error ? <div className="card">{error}</div> : null}

      {data?.attention.length ? (
        <div className="card" style={{ background: "#fffdf4", borderColor: "var(--warn-line)", marginBottom: 14 }}>
          <div className="card-title" style={{ marginBottom: 6 }}>
            Needs attention
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {data.attention.map((item) => (
              <div className="spread" key={item.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{item.title}</div>
                  <div className="row-sub">{item.detail}</div>
                </div>
                <Link href={item.href} className="btn sm" style={{ marginLeft: "auto" }}>
                  {item.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="stats">
        <Stat label="Active automations" value={data?.stats.active_agents ?? "—"} foot={`${data?.stats.agents ?? 0} total`} />
        <Stat label="Messages today" value={data?.stats.messages_today ?? "—"} foot="inbound + outbound" />
        <Stat label="Runs today" value={data?.stats.runs_today ?? "—"} foot={`${data?.stats.queued ?? 0} queued`} />
        <Stat label="Follow-ups sent" value={data?.stats.followups_sent ?? "—"} foot="all time" />
      </div>

      <div className="grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.45fr) minmax(0,1fr)", gap: 14, marginTop: 14 }}>
        <div className="card">
          <div className="card-title">Recent runs</div>
          <div className="card-sub" style={{ marginBottom: 10 }}>
            Every agent turn, with the tools it used.
          </div>
          {data?.recent_runs.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Reply</th>
                  <th>Steps</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Pill tone={STATUS_TONE[run.status]}>{run.status}</Pill>
                    </td>
                    <td style={{ maxWidth: 300 }}>
                      <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 280 }}>
                        {run.reply || <span className="muted">no reply</span>}
                      </div>
                      <div className="row-sub">
                        {run.trigger} · {run.tokens} tokens
                      </div>
                    </td>
                    <td>{run.iterations}</td>
                    <td className="muted">{timeAgo(run.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">
              <strong>No runs yet</strong>
              Send a message from the Assistant to see the agent think.
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title">Chats</div>
          <div className="card-sub" style={{ marginBottom: 10 }}>
            Where the agent is working.
          </div>
          <div className="room-list">
            {(data?.rooms ?? []).map((room) => (
              <Link key={room.id} href="/dashboard/assistant" className="room">
                <span className="avatar" style={{ width: 28, height: 28, fontSize: 11 }}>
                  {initials(room.display_name)}
                </span>
                <span style={{ minWidth: 0 }}>
                  <span className="room-name">{room.display_name}</span>
                  <span className="room-meta" style={{ display: "block" }}>
                    {room.kind} · {timeAgo(room.last_activity_at)}
                  </span>
                </span>
              </Link>
            ))}
            {!data?.rooms.length ? <div className="muted">No chats yet.</div> : null}
          </div>
          <div className="divider" />
          <Link href="/dashboard/assistant" className="btn ghost" style={{ width: "100%" }}>
            <MessageSquare /> Open the assistant
          </Link>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div className="card-title">How it works</div>
          <div className="row-sub">
            Inbound message → gates → the agent runs with tools → reply is admitted and delivered. Watch it happen in
            Activity.
          </div>
        </div>
        <Link href="/dashboard/activity" className="btn ghost sm">
          View activity <ArrowRight />
        </Link>
      </div>
    </>
  );
}
