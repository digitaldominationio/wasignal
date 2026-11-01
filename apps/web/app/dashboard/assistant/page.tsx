"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Paperclip, QrCode, Send, UserRound } from "lucide-react";

import { ApiError, Message, Room, SendResult, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { clockTime, dayKey, dayLabel, initials } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

export default function AssistantPage() {
  const { accountId } = useWorkspace();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const loadRooms = useCallback(async () => {
    if (!accountId) return;
    const data = await api<{ items: Room[] }>("/dashboard/rooms", { accountId });
    setRooms(data.items);
    setActiveId((current) => {
      if (current !== null && data.items.some((room) => room.id === current)) return current;
      const system = data.items.find((room) => room.kind === "system");
      return system?.id ?? data.items[0]?.id ?? null;
    });
  }, [accountId]);

  const loadMessages = useCallback(
    async (id: number) => {
      if (!accountId) return;
      const data = await api<{ items: Message[] }>(`/dashboard/chat/messages?room_id=${id}&limit=100`, { accountId });
      setMessages([...data.items].reverse());
    },
    [accountId],
  );

  useEffect(() => {
    loadRooms().catch((cause) => setError((cause as ApiError).detail));
  }, [loadRooms]);

  useEffect(() => {
    if (!activeId) return;
    void loadMessages(activeId).catch(() => undefined);
    const timer = setInterval(() => void loadMessages(activeId).catch(() => undefined), 3000);
    return () => clearInterval(timer);
  }, [activeId, loadMessages]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim() || !activeId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api<SendResult>("/dashboard/chat/messages", {
        method: "POST",
        accountId,
        body: { text, room_id: activeId },
      });
      setText("");
      setNotice(`turn ${result.stage} · run #${result.run_id ?? "—"} · ${result.delivery}`);
      await loadMessages(activeId);
    } catch (cause) {
      const err = cause as ApiError;
      setError(
        err.status === 409
          ? "The agent didn't take this message: it may be handed over to a human, or no automation matches."
          : err.detail,
      );
    } finally {
      setBusy(false);
    }
  }

  async function ownerReply() {
    if (!activeId) return;
    try {
      await api(`/dashboard/rooms/${activeId}/owner-reply?text=${encodeURIComponent("I'll take this one")}`, {
        method: "POST",
        accountId,
      });
      setNotice("Human reply recorded — auto-replies pause for 10 minutes.");
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  const activeRoom = rooms.find((room) => room.id === activeId);
  const isInbox = activeRoom?.kind === "system";

  const grouped = useMemo(() => {
    const groups: { key: string; label: string; items: Message[] }[] = [];
    for (const message of messages) {
      const key = dayKey(message.ts);
      const last = groups[groups.length - 1];
      if (last?.key === key) last.items.push(message);
      else groups.push({ key, label: dayLabel(message.ts), items: [message] });
    }
    return groups;
  }, [messages]);

  return (
    <>
      <PageHeader
        title="Assistant"
        subtitle="Your inbox: OTPs, connection alerts, and the main agent."
        action={
          !isInbox && activeRoom ? (
            <button className="btn ghost sm" onClick={ownerReply}>
              <UserRound /> Simulate human reply
            </button>
          ) : null
        }
      />

      <div className="room-chips">
        {rooms.map((room) => (
          <button
            key={room.id}
            className={`chip tab ${room.id === activeId ? "on" : ""}`}
            onClick={() => setActiveId(room.id)}
          >
            {room.kind === "system" ? "Assistant inbox" : room.display_name}
          </button>
        ))}
      </div>

      <div className="inbox card">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <span className="avatar" style={{ width: 30, height: 30, fontSize: 11 }}>
            {isInbox ? "W" : initials(activeRoom?.display_name)}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="card-title">{isInbox ? "Wasignal" : activeRoom?.display_name ?? "Conversation"}</div>
            <div className="card-sub">{isInbox ? "System notifications and service alerts" : activeRoom?.external_id}</div>
          </div>
          {isInbox ? <Pill>bot</Pill> : <Pill tone="ok">agent watching</Pill>}
        </div>

        <div className="inbox-thread" ref={scrollRef}>
          {grouped.map((group) => (
            <div key={group.key} style={{ display: "contents" }}>
              <div className="day-divider">
                {group.label} · {clockTime(group.items[0].ts)}
              </div>
              {group.items.map((message) => (
                <div key={message.id} className={`bubble ${message.direction}`}>
                  {message.text}
                  {message.media?.length
                    ? message.media.map((media, index) => (
                        <span className="attachment" key={`${message.id}-${index}`}>
                          <QrCode />
                          <span>
                            {media.name ?? media.type ?? "Attachment"}
                            <span className="sub" style={{ display: "block" }}>
                              {media.url ? "Tap to open" : "Attachment unavailable or loading"}
                            </span>
                          </span>
                        </span>
                      ))
                    : null}
                  <span className="bubble-meta">
                    {clockTime(message.ts)} · {message.status}
                    {message.source !== "whatsapp" ? ` · ${message.source}` : ""}
                  </span>
                </div>
              ))}
            </div>
          ))}
          {messages.length === 0 ? <div className="muted">Nothing here yet.</div> : null}
        </div>

        <form className="composer-shell" onSubmit={send}>
          <div className="composer-pill">
            <button
              type="button"
              className="icon-btn"
              title="Attachments aren't wired in this scaffold"
              onClick={() => setNotice("Attachments require the media pipeline (docs/BRIDGE.md).")}
            >
              <Paperclip />
            </button>
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Show my active automations"
              aria-label="Message"
            />
            <button className="send-btn" type="submit" disabled={busy || !text.trim()} aria-label="Send">
              <Send style={{ width: 16, height: 16 }} />
            </button>
          </div>
          {notice ? <p className="notice">{notice}</p> : null}
          {error ? <p className="error">{error}</p> : null}
        </form>
      </div>
    </>
  );
}
