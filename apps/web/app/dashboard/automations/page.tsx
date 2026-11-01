"use client";

import { useCallback, useEffect, useState } from "react";
import { Mic, Pause, Play, Plus, Send, Sparkles } from "lucide-react";

import { Agent, ApiError, ModelInfo, Room, api } from "@/lib/api";
import { EmptyState, Field, Modal, PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

const CAPABILITIES: { id: string; label: string; hint: string }[] = [
  { id: "read", label: "Read", hint: "Read the scoped chat" },
  { id: "send", label: "Read & send", hint: "Reply with text and media" },
  { id: "send_other", label: "Send to other chats", hint: "Post in chats other than the trigger chat" },
  { id: "group_admin", label: "Group admin", hint: "Add/remove members, change settings" },
];

type CreateForm = {
  name: string;
  system_prompt: string;
  trigger_type: "event" | "scheduled" | "hybrid";
  trigger_scope: "room" | "topic";
  trigger_condition: string;
  chat_type: "all" | "dm" | "group";
  room_id: string;
  capabilities: string[];
  llm_model: string;
};

const EMPTY_FORM: CreateForm = {
  name: "",
  system_prompt: "",
  trigger_type: "event",
  trigger_scope: "room",
  trigger_condition: "",
  chat_type: "all",
  room_id: "",
  capabilities: ["read", "send"],
  llm_model: "",
};

export default function AutomationsPage() {
  const { accountId } = useWorkspace();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsReady, setModelsReady] = useState(false);
  const [providerName, setProviderName] = useState("echo");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<Agent | null>(null);
  const [testText, setTestText] = useState("What is the fee for the dropper batch?");
  const [testReply, setTestReply] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [agentData, roomData] = await Promise.all([
        api<{ items: Agent[] }>("/dashboard/agents", { accountId }),
        api<{ items: Room[] }>("/dashboard/rooms", { accountId }),
      ]);
      setAgents(agentData.items);
      setRooms(roomData.items);
      try {
        const providers = await api<{ provider: string; openrouter: { configured: boolean } }>(
          "/dashboard/models/providers",
          { accountId },
        );
        setProviderName(providers.provider);
        setModelsReady(providers.openrouter.configured);
        if (providers.openrouter.configured) {
          const catalogue = await api<{ items: ModelInfo[] }>("/dashboard/models?limit=400", { accountId });
          setModels(catalogue.items);
        }
      } catch {
        setModelsReady(false);
      }
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function createAgent(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      await api("/dashboard/agents", {
        method: "POST",
        accountId,
        body: {
          name: form.name,
          system_prompt: form.system_prompt,
          trigger_type: form.trigger_type,
          trigger_scope: form.trigger_scope,
          trigger_condition: form.trigger_condition || null,
          chat_type: form.chat_type,
          room_id: form.room_id ? Number(form.room_id) : null,
          capabilities: form.capabilities,
          llm_provider: form.llm_model ? "openrouter" : null,
          llm_model: form.llm_model || null,
        },
      });
      setCreating(false);
      setForm(EMPTY_FORM);
      setNotice("Automation created — it is live now.");
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(agent: Agent) {
    if (!accountId) return;
    try {
      const updated = await api<Agent>(`/dashboard/agents/${agent.id}/toggle-status`, { method: "POST", accountId });
      setAgents((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function pinModel(agent: Agent, modelId: string) {
    if (!accountId || !modelId) return;
    try {
      const updated = await api<Agent>(`/dashboard/agents/${agent.id}`, {
        method: "PATCH",
        accountId,
        body: { llm_provider: "openrouter", llm_model: modelId },
      });
      setAgents((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function runTest(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId || !testing) return;
    setTestReply(null);
    try {
      const result = await api<{ status: string; reply: string; iterations: number; tokens: number }>(
        "/dashboard/agents/test-run",
        { method: "POST", accountId, body: { agent_id: testing.id, system_prompt: testing.system_prompt, trigger_message: testText } },
      );
      setTestReply(`${result.reply}\n\n— ${result.status} · ${result.iterations} step(s) · ${result.tokens} tokens`);
    } catch (cause) {
      setTestReply((cause as ApiError).detail);
    }
  }

  return (
    <>
      <PageHeader
        title="Automations"
        subtitle="Plain-English instructions plus a trigger. Each one is an agent with its own permissions."
        action={
          <button className="btn" onClick={() => setCreating(true)}>
            <Plus /> New automation
          </button>
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {notice ? <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)", marginBottom: 14 }}>{notice}</div> : null}

      {agents.length === 0 ? (
        <EmptyState
          title="No automations yet"
          detail="Start with the admissions template: answer pricing questions from your price list, then follow up on quiet leads."
          action={
            <button className="btn" onClick={() => setCreating(true)}>
              <Sparkles /> Create the first one
            </button>
          }
        />
      ) : null}

      {agents.map((agent) => (
        <div className="card" key={agent.id}>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="item-title" style={{ fontSize: 15 }}>
                {agent.name}
                <Pill tone={agent.status === "active" ? "ok" : undefined}>{agent.status}</Pill>
                <Pill>{agent.trigger_type}</Pill>
                <Pill>{agent.chat_type === "all" ? "all chats" : `${agent.chat_type}s`}</Pill>
              </div>
              <div className="row-sub">
                {agent.trigger_scope === "topic" && agent.trigger_condition
                  ? `matches: ${agent.trigger_condition}`
                  : agent.room_id
                    ? `only in ${rooms.find((room) => room.id === agent.room_id)?.display_name ?? `room ${agent.room_id}`}`
                    : "every matching chat"}
              </div>
            </div>

            <div className="row-action">
              <button className="btn ghost sm" onClick={() => { setTesting(agent); setTestReply(null); }}>
                <Send /> Test
              </button>
              <button className="btn ghost sm" onClick={() => toggle(agent)}>
                {agent.status === "active" ? <><Pause /> Pause</> : <><Play /> Activate</>}
              </button>
            </div>
          </div>

          <div className="divider" />

          <div className="chips" style={{ marginBottom: 10 }}>
            {agent.capabilities.map((capability) => (
              <span className="chip on" key={capability} style={{ cursor: "default" }}>
                {CAPABILITIES.find((item) => item.id === capability)?.label ?? capability}
              </span>
            ))}
            {agent.capabilities.length === 0 ? <span className="muted">No capabilities</span> : null}
          </div>

          <div className="two-col">
            <label className="field">
              <span>Model</span>
              {modelsReady ? (
                <select value={agent.llm_model ?? ""} onChange={(event) => pinModel(agent, event.target.value)}>
                  <option value="">deployment default</option>
                  {models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.free ? "free · " : ""}
                      {model.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input value={`deployment default (${providerName})`} readOnly />
              )}
            </label>
            <div className="field">
              <span>Instructions</span>
              <div className="row-sub" style={{ marginTop: 4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                {agent.system_prompt}
              </div>
            </div>
          </div>
        </div>
      ))}

      {creating ? (
        <Modal title="New automation" onClose={() => setCreating(false)}>
          <form className="form" onSubmit={createAgent}>
            <Field label="Name">
              <input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Admissions counsellor" />
            </Field>
            <Field label="Instructions (plain English)">
              <textarea
                required
                rows={5}
                value={form.system_prompt}
                onChange={(event) => setForm({ ...form, system_prompt: event.target.value })}
                placeholder="You are the admissions counsellor for… Answer fee, batch and hostel questions from the knowledge base. Qualify the lead, then book a counselling slot."
              />
            </Field>

            <div className="two-col">
              <Field label="Trigger">
                <select value={form.trigger_type} onChange={(event) => setForm({ ...form, trigger_type: event.target.value as CreateForm["trigger_type"] })}>
                  <option value="event">When a message matches</option>
                  <option value="scheduled">On a schedule</option>
                  <option value="hybrid">Both</option>
                </select>
              </Field>
              <Field label="Scope">
                <select value={form.trigger_scope} onChange={(event) => setForm({ ...form, trigger_scope: event.target.value as CreateForm["trigger_scope"] })}>
                  <option value="room">This chat / all chats</option>
                  <option value="topic">Only matching topics</option>
                </select>
              </Field>
            </div>

            <div className="two-col">
              <Field label="Where it works">
                <select value={form.chat_type} onChange={(event) => setForm({ ...form, chat_type: event.target.value as CreateForm["chat_type"] })}>
                  <option value="all">All chats</option>
                  <option value="dm">Direct messages only</option>
                  <option value="group">Groups only</option>
                </select>
              </Field>
              <Field label="Single chat (optional)">
                <select value={form.room_id} onChange={(event) => setForm({ ...form, room_id: event.target.value })}>
                  <option value="">Every chat</option>
                  {rooms.map((room) => (
                    <option key={room.id} value={room.id}>
                      {room.display_name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            {form.trigger_scope === "topic" ? (
              <Field label="Message match (keywords)">
                <input value={form.trigger_condition} onChange={(event) => setForm({ ...form, trigger_condition: event.target.value })} placeholder="fees, price, batch, hostel" />
              </Field>
            ) : null}

            <div className="field">
              <span>Capabilities</span>
              <div className="chips">
                {CAPABILITIES.map((capability) => {
                  const on = form.capabilities.includes(capability.id);
                  return (
                    <button
                      type="button"
                      key={capability.id}
                      className={`chip ${on ? "on" : ""}`}
                      title={capability.hint}
                      onClick={() =>
                        setForm({
                          ...form,
                          capabilities: on
                            ? form.capabilities.filter((item) => item !== capability.id)
                            : [...form.capabilities, capability.id],
                        })
                      }
                    >
                      {capability.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {modelsReady ? (
              <Field label="Model">
                <select value={form.llm_model} onChange={(event) => setForm({ ...form, llm_model: event.target.value })}>
                  <option value="">Deployment default</option>
                  {models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.free ? "free · " : ""}
                      {model.name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button type="button" className="btn ghost" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button type="submit" className="btn" disabled={busy}>
                {busy ? "Creating…" : "Create automation"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {testing ? (
        <Modal title={`Test — ${testing.name}`} onClose={() => setTesting(null)}>
          <form className="form" onSubmit={runTest}>
            <p className="muted">
              Runs the agent against a message with WhatsApp side effects intercepted. Nothing is sent.
            </p>
            <Field label="Customer message">
              <textarea rows={3} value={testText} onChange={(event) => setTestText(event.target.value)} />
            </Field>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" type="submit">
                <Mic /> Run test
              </button>
            </div>
            {testReply ? (
              <div className="card" style={{ background: "#fbfbf9" }}>
                <div className="card-sub">Output</div>
                <pre style={{ whiteSpace: "pre-wrap", margin: "6px 0 0", fontFamily: "inherit", fontSize: 13 }}>
                  {testReply}
                </pre>
              </div>
            ) : null}
          </form>
        </Modal>
      ) : null}
    </>
  );
}
