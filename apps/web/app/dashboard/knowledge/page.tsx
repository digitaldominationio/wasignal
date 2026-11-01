"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Plus } from "lucide-react";

import { ApiError, Room, api } from "@/lib/api";
import { EmptyState, Field, Modal, PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

type Source = {
  id: number;
  name: string;
  source_room_id: string;
  source_type: string;
  extraction_instruction: string;
  status: string;
};

type Entry = { id: number; title: string; content: string; keys: string[] };

export default function KnowledgePage() {
  const { accountId } = useWorkspace();
  const [sources, setSources] = useState<Source[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [entries, setEntries] = useState<Record<number, Entry[]>>({});
  const [creating, setCreating] = useState(false);
  const [entryFor, setEntryFor] = useState<Source | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceForm, setSourceForm] = useState({ name: "", room: "", instruction: "" });
  const [entryForm, setEntryForm] = useState({ title: "", content: "", keys: "" });

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [sourceData, roomData] = await Promise.all([
        api<{ items: Source[] }>("/dashboard/knowledge-sources", { accountId }),
        api<{ items: Room[] }>("/dashboard/rooms", { accountId }),
      ]);
      setSources(sourceData.items);
      setRooms(roomData.items);
      setSourceForm((current) => ({ ...current, room: current.room || roomData.items[0]?.external_id || "" }));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(source: Source) {
    if (open === source.id) {
      setOpen(null);
      return;
    }
    setOpen(source.id);
    if (!entries[source.id]) {
      try {
        const data = await api<{ items: Entry[] }>(`/dashboard/knowledge-sources/${source.id}/entries`, { accountId });
        setEntries((current) => ({ ...current, [source.id]: data.items }));
      } catch (cause) {
        setError((cause as ApiError).detail);
      }
    }
  }

  async function createSource(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId) return;
    try {
      await api("/dashboard/knowledge-sources", {
        method: "POST",
        accountId,
        body: {
          name: sourceForm.name,
          source_room_id: sourceForm.room,
          source_type: "whatsapp_room",
          extraction_instruction: sourceForm.instruction,
        },
      });
      setCreating(false);
      setSourceForm({ name: "", room: rooms[0]?.external_id ?? "", instruction: "" });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function createEntry(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId || !entryFor) return;
    try {
      const created = await api<Entry>(`/dashboard/knowledge-sources/${entryFor.id}/entries`, {
        method: "POST",
        accountId,
        body: {
          title: entryForm.title,
          content: entryForm.content,
          keys: entryForm.keys.split(",").map((key) => key.trim()).filter(Boolean),
        },
      });
      setEntries((current) => ({ ...current, [entryFor.id]: [...(current[entryFor.id] ?? []), created] }));
      setOpen(entryFor.id);
      setEntryFor(null);
      setEntryForm({ title: "", content: "", keys: "" });
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  return (
    <>
      <PageHeader
        title="Knowledge"
        subtitle="Point at a chat, extract the facts, and the agent answers from them instead of guessing."
        action={
          <button className="btn" onClick={() => setCreating(true)}>
            <Plus /> Add source
          </button>
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}

      {sources.length === 0 ? (
        <EmptyState
          title="No knowledge yet"
          detail="Paste your price list into a chat, then add that chat as a source. Extraction turns it into entries."
          action={
            <button className="btn" onClick={() => setCreating(true)}>
              <FileText /> Add the first source
            </button>
          }
        />
      ) : null}

      {sources.map((source) => (
        <div className="card" key={source.id}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button className="btn ghost sm" onClick={() => toggle(source)}>
              {open === source.id ? <ChevronDown /> : <ChevronRight />}
            </button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="item-title">
                {source.name}
                <Pill tone="ok">{source.status}</Pill>
              </div>
              <div className="row-sub">
                {source.source_type} · {source.source_room_id}
                {entries[source.id] ? ` · ${entries[source.id].length} entries` : ""}
              </div>
            </div>
            <div className="row-action">
              <button className="btn ghost sm" onClick={() => setEntryFor(source)}>
                <Plus /> Entry
              </button>
            </div>
          </div>

          {source.extraction_instruction ? (
            <div className="row-sub" style={{ marginTop: 8 }}>
              Extract: {source.extraction_instruction}
            </div>
          ) : null}

          {open === source.id ? (
            entries[source.id]?.length ? (
              <table className="table" style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Keys</th>
                    <th>Content</th>
                  </tr>
                </thead>
                <tbody>
                  {entries[source.id].map((entry) => (
                    <tr key={entry.id}>
                      <td style={{ fontWeight: 550 }}>{entry.title || "—"}</td>
                      <td>
                        <div className="chips">
                          {entry.keys.map((key) => (
                            <span className="pill" key={key}>
                              {key}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td style={{ maxWidth: 420 }}>{entry.content}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="muted" style={{ marginTop: 10 }}>
                No entries extracted yet.
              </div>
            )
          ) : null}
        </div>
      ))}

      {creating ? (
        <Modal title="Add knowledge source" onClose={() => setCreating(false)}>
          <form className="form" onSubmit={createSource}>
            <Field label="Name">
              <input required value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} placeholder="Fee & batch details" />
            </Field>
            <Field label="Source chat">
              <select value={sourceForm.room} onChange={(event) => setSourceForm({ ...sourceForm, room: event.target.value })}>
                {rooms.map((room) => (
                  <option key={room.id} value={room.external_id}>
                    {room.display_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Extraction instruction">
              <textarea
                rows={3}
                value={sourceForm.instruction}
                onChange={(event) => setSourceForm({ ...sourceForm, instruction: event.target.value })}
                placeholder="Extract every batch, fee, hostel charge and scholarship rule."
              />
            </Field>
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button className="btn" type="submit">
                Add source
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {entryFor ? (
        <Modal title={`Add entry — ${entryFor.name}`} onClose={() => setEntryFor(null)}>
          <form className="form" onSubmit={createEntry}>
            <Field label="Title">
              <input value={entryForm.title} onChange={(event) => setEntryForm({ ...entryForm, title: event.target.value })} placeholder="NEET dropper batch 2026" />
            </Field>
            <Field label="Content">
              <textarea required rows={4} value={entryForm.content} onChange={(event) => setEntryForm({ ...entryForm, content: event.target.value })} placeholder="Starts 15 July. ₹1,45,000 for the year. EMI available." />
            </Field>
            <Field label="Keys (comma separated)">
              <input value={entryForm.keys} onChange={(event) => setEntryForm({ ...entryForm, keys: event.target.value })} placeholder="neet, dropper, fee" />
            </Field>
            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setEntryFor(null)}>
                Cancel
              </button>
              <button className="btn" type="submit">
                Add entry
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </>
  );
}
