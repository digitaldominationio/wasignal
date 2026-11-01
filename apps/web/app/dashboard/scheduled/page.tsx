"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Plus } from "lucide-react";

import { ApiError, Room, api } from "@/lib/api";
import { EmptyState, Field, Modal, PageHeader, Pill } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

type Job = {
  id: number;
  context: { type?: string; message?: string; room_id?: number };
  rrule: string;
  dtstart_local: string;
  next_run_at: number | null;
  enabled: number;
  last_fired_at: number | null;
};

type Task = {
  id: number;
  context: { message?: string; room_id?: number };
  execute_after_at: number;
  status: string;
};

export default function ScheduledPage() {
  const { accountId } = useWorkspace();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    room_id: "",
    message: "",
    when: "",
    repeat: "once",
  });

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [jobData, taskData, roomData] = await Promise.all([
        api<{ items: Job[] }>("/dashboard/jobs", { accountId }),
        api<{ items: Task[] }>("/dashboard/tasks", { accountId }),
        api<{ items: Room[] }>("/dashboard/rooms", { accountId }),
      ]);
      setJobs(jobData.items);
      setTasks(taskData.items);
      setRooms(roomData.items);
      setForm((current) => ({ ...current, room_id: current.room_id || String(roomData.items[0]?.id ?? "") }));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  function rruleFor(when: string, repeat: string): string | null {
    const [, timePart = "09:00"] = when.split("T");
    const [hour, minute] = timePart.split(":");
    if (repeat === "daily") return `FREQ=DAILY;BYHOUR=${Number(hour)};BYMINUTE=${Number(minute)}`;
    if (repeat === "weekdays") return `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=${Number(hour)};BYMINUTE=${Number(minute)}`;
    return null;
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      const context = {
        type: "scheduled_whatsapp_message",
        room_id: Number(form.room_id),
        message: form.message,
      };
      const rrule = rruleFor(form.when, form.repeat);
      if (rrule) {
        await api("/dashboard/jobs", {
          method: "POST",
          accountId,
          body: { context, rrule, dtstart_local: form.when },
        });
      } else {
        await api("/dashboard/tasks", {
          method: "POST",
          accountId,
          body: { context, execute_after_local: form.when },
        });
      }
      setCreating(false);
      setForm({ room_id: String(rooms[0]?.id ?? ""), message: "", when: "", repeat: "once" });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(false);
    }
  }

  async function toggleJob(job: Job) {
    if (!accountId) return;
    await api(`/dashboard/jobs/${job.id}/toggle-status`, { method: "POST", accountId });
    await load();
  }

  async function pauseTask(task: Task) {
    if (!accountId) return;
    await api(`/dashboard/tasks/${task.id}/pause`, { method: "POST", accountId });
    await load();
  }

  return (
    <>
      <PageHeader
        title="Scheduled messages"
        subtitle="One-time and recurring sends. They go out even when your phone is offline."
        action={
          <button className="btn" onClick={() => setCreating(true)}>
            <Plus /> New scheduled message
          </button>
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      <div className="card">
        <div className="spread" style={{ display: "flex", alignItems: "center" }}>
          <div>
            <div className="card-title">Recurring</div>
            <div className="card-sub">Jobs with an iCalendar rule.</div>
          </div>
          <Pill>{jobs.length}</Pill>
        </div>
        {jobs.length ? (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Message</th>
                <th>Chat</th>
                <th>Rule</th>
                <th>Next</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td style={{ maxWidth: 320 }}>{job.context.message}</td>
                  <td className="muted">{rooms.find((room) => room.id === job.context.room_id)?.display_name ?? "—"}</td>
                  <td className="muted">{job.rrule || "one-off"}</td>
                  <td>{job.next_run_at ? dateTime(job.next_run_at) : "—"}</td>
                  <td>
                    <button className="btn ghost sm" onClick={() => toggleJob(job)}>
                      {job.enabled ? "Pause" : "Resume"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ marginTop: 12 }}>
            <EmptyState title="Nothing recurring" detail="Daily standups, weekly reminders, renewal nudges." />
          </div>
        )}
      </div>

      <div className="card">
        <div className="spread" style={{ display: "flex", alignItems: "center" }}>
          <div>
            <div className="card-title">One-off</div>
            <div className="card-sub">Queued tasks that fire once.</div>
          </div>
          <Pill>{tasks.length}</Pill>
        </div>
        {tasks.length ? (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Message</th>
                <th>Chat</th>
                <th>When</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td style={{ maxWidth: 320 }}>{task.context.message}</td>
                  <td className="muted">{rooms.find((room) => room.id === task.context.room_id)?.display_name ?? "—"}</td>
                  <td>{dateTime(task.execute_after_at)}</td>
                  <td>
                    <Pill tone={task.status === "pending" ? "warn" : task.status === "done" ? "ok" : undefined}>
                      {task.status}
                    </Pill>
                  </td>
                  <td>
                    {task.status === "pending" ? (
                      <button className="btn ghost sm" onClick={() => pauseTask(task)}>
                        Pause
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ marginTop: 12 }}>
            <EmptyState title="No one-off messages" detail="A reminder for tomorrow morning, a follow-up for Monday." />
          </div>
        )}
      </div>

      {creating ? (
        <Modal title="New scheduled message" onClose={() => setCreating(false)}>
          <form className="form" onSubmit={create}>
            <Field label="Chat">
              <select required value={form.room_id} onChange={(event) => setForm({ ...form, room_id: event.target.value })}>
                {rooms.map((room) => (
                  <option key={room.id} value={room.id}>
                    {room.display_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Message">
              <textarea required rows={3} value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} placeholder="Good morning! Quick reminder about today's class." />
            </Field>
            <div className="two-col">
              <Field label="When">
                <input required type="datetime-local" value={form.when} onChange={(event) => setForm({ ...form, when: event.target.value })} />
              </Field>
              <Field label="Repeat">
                <select value={form.repeat} onChange={(event) => setForm({ ...form, repeat: event.target.value })}>
                  <option value="once">Once</option>
                  <option value="daily">Every day</option>
                  <option value="weekdays">Weekdays</option>
                </select>
              </Field>
            </div>
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button className="btn" type="submit" disabled={busy}>
                <CalendarClock /> {busy ? "Scheduling…" : "Schedule"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </>
  );
}
