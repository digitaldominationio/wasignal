"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { PageHeader, Pill, Stat } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

type Activity = {
  by_day: { day: string; direction: string; n: number }[];
  runs_by_status: Record<string, number>;
};

type Overview = {
  stats: {
    messages_today: number;
    runs_today: number;
    followups_sent: number;
    queued: number;
    agents: number;
    rooms: number;
  };
};

export default function InsightsPage() {
  const { accountId } = useWorkspace();
  const [activity, setActivity] = useState<Activity | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) return;
    Promise.all([
      api<Activity>("/dashboard/insights/activity", { accountId }),
      api<Overview>("/dashboard/overview", { accountId }),
    ])
      .then(([activityData, overviewData]) => {
        setActivity(activityData);
        setOverview(overviewData);
      })
      .catch((cause) => setError((cause as ApiError).detail));
  }, [accountId]);

  const days = useMemo(() => {
    const map = new Map<string, { in: number; out: number }>();
    for (const row of activity?.by_day ?? []) {
      const entry = map.get(row.day) ?? { in: 0, out: 0 };
      if (row.direction === "in") entry.in += row.n;
      else entry.out += row.n;
      map.set(row.day, entry);
    }
    return [...map.entries()].slice(0, 10).reverse();
  }, [activity]);

  const max = Math.max(1, ...days.map(([, value]) => Math.max(value.in, value.out)));

  return (
    <>
      <PageHeader title="Insights" subtitle="How much conversation there is, and what the agents are doing with it." />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      <div className="stats">
        <Stat label="Messages today" value={overview?.stats.messages_today ?? "—"} />
        <Stat label="Runs today" value={overview?.stats.runs_today ?? "—"} />
        <Stat label="Follow-ups sent" value={overview?.stats.followups_sent ?? "—"} />
        <Stat label="Queued" value={overview?.stats.queued ?? "—"} />
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-title">Messages by day</div>
        <div className="card-sub">Inbound vs outbound, from the message store.</div>

        {days.length ? (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 14, height: 180, marginTop: 18, padding: "0 4px" }}>
            {days.map(([day, value]) => (
              <div key={day} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 130 }}>
                  <div
                    title={`${value.in} in`}
                    style={{ width: 12, height: `${(value.in / max) * 100}%`, background: "#cfcfc4", borderRadius: "4px 4px 0 0" }}
                  />
                  <div
                    title={`${value.out} out`}
                    style={{ width: 12, height: `${(value.out / max) * 100}%`, background: "#111110", borderRadius: "4px 4px 0 0" }}
                  />
                </div>
                <span className="muted" style={{ fontSize: 10.5 }}>
                  {day.slice(5)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 12 }}>
            No messages yet.
          </div>
        )}

        <div className="row" style={{ gap: 14, marginTop: 12 }}>
          <span className="row" style={{ gap: 6 }}>
            <span style={{ width: 9, height: 9, background: "#cfcfc4", borderRadius: 2 }} />
            <span className="muted">inbound</span>
          </span>
          <span className="row" style={{ gap: 6 }}>
            <span style={{ width: 9, height: 9, background: "#111110", borderRadius: 2 }} />
            <span className="muted">outbound</span>
          </span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Runs by status</div>
        <div className="chips" style={{ marginTop: 10 }}>
          {Object.entries(activity?.runs_by_status ?? {}).length ? (
            Object.entries(activity!.runs_by_status).map(([status, count]) => (
              <span className="chip" key={status} style={{ cursor: "default" }}>
                {status}
                <Pill>{count}</Pill>
              </span>
            ))
          ) : (
            <span className="muted">No runs yet.</span>
          )}
        </div>
        <div className="row" style={{ gap: 8, marginTop: 14 }}>
          <Pill>{overview?.stats.agents ?? 0} automations</Pill>
          <Pill>{overview?.stats.rooms ?? 0} chats</Pill>
        </div>
      </div>
    </>
  );
}
