"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";

import { ApiError, Room, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

export default function ExcludedPage() {
  const { accountId } = useWorkspace();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const data = await api<{ items: Room[] }>("/dashboard/rooms", { accountId });
      setRooms(data.items);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(room: Room) {
    if (!accountId) return;
    try {
      if (room.is_excluded) {
        await api(`/dashboard/chat-exclusions/${room.id}`, { method: "DELETE", accountId });
      } else {
        await api("/dashboard/chat-exclusions", {
          method: "POST",
          accountId,
          body: { room_ids: [room.id], duration_seconds: 31_536_000 },
        });
      }
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  const excluded = rooms.filter((room) => room.is_excluded).length;

  return (
    <>
      <PageHeader
        title="Excluded chats"
        subtitle="Loop2 never reads or replies here — not even if another automation has send-to-other-chats."
        action={<Pill tone="ok">{excluded} excluded</Pill>}
      />

      <div className="card" style={{ background: "#fbfbf9", marginBottom: 14 }}>
        <div className="row" style={{ gap: 8, alignItems: "flex-start" }}>
          <ShieldCheck style={{ width: 16, height: 16, color: "var(--ok)", marginTop: 2 }} />
          <div className="muted">
            Do this before enabling an automation on “all direct messages”. Exclusion is applied at read time, so the
            message never reaches the model.
          </div>
        </div>
      </div>

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      {rooms.map((room) => (
        <div className="item-row" key={room.id} style={{ marginTop: 8 }}>
          <span className="item-icon">{room.is_excluded ? <EyeOff /> : <Eye />}</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="item-title">
              {room.display_name}
              {room.is_excluded ? <Pill tone="warn">excluded</Pill> : <Pill>visible</Pill>}
            </div>
            <div className="row-sub">
              {room.kind} · {room.external_id}
            </div>
          </div>
          <div className="row-action">
            <button className={room.is_excluded ? "btn ghost sm" : "btn sm"} onClick={() => toggle(room)}>
              {room.is_excluded ? "Include again" : "Exclude"}
            </button>
          </div>
        </div>
      ))}
    </>
  );
}
