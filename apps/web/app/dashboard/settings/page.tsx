"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, ExternalLink, KeyRound, Trash2 } from "lucide-react";

import { ApiError, ModelInfo, ProviderInfo, ProvidersResponse, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

export default function SettingsPage() {
  const { accountId } = useWorkspace();
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string>("");
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const providers = await api<ProvidersResponse>("/dashboard/providers", { accountId });
      setData(providers);
      setDefaultProvider(providers.default_provider ?? "");
      setDefaultModel(providers.default_model ?? "");
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!accountId) return;
    const provider = defaultProvider || data?.items.find((item) => item.configured)?.id;
    if (!provider) {
      setModels([]);
      return;
    }
    api<{ items: ModelInfo[] }>(`/dashboard/models?limit=400&provider=${provider}`, { accountId })
      .then((catalogue) => setModels(catalogue.items))
      .catch(() => setModels([]));
  }, [accountId, defaultProvider, data]);

  async function saveKey(provider: ProviderInfo) {
    if (!accountId) return;
    const value = (keys[provider.id] ?? "").trim();
    if (!value) {
      setError("Paste the key first.");
      return;
    }
    setBusy(provider.id);
    setError(null);
    setNotice(null);
    try {
      const result = await api<{ valid: boolean; message: string; models: number }>(
        `/dashboard/providers/${provider.id}`,
        { method: "PUT", accountId, body: { api_key: value } },
      );
      setKeys((current) => ({ ...current, [provider.id]: "" }));
      setNotice(
        result.valid
          ? `${provider.label} connected · ${result.models} models available.`
          : `${provider.label} key saved but validation failed: ${result.message}`,
      );
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(null);
    }
  }

  async function testKey(provider: ProviderInfo) {
    if (!accountId) return;
    setBusy(provider.id);
    setError(null);
    try {
      const result = await api<{ valid: boolean; message: string; models: number }>(
        `/dashboard/providers/${provider.id}/test`,
        { method: "POST", accountId },
      );
      setNotice(result.valid ? `${provider.label} key works · ${result.models} models.` : `${provider.label}: ${result.message}`);
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(null);
    }
  }

  async function removeKey(provider: ProviderInfo) {
    if (!accountId) return;
    if (!window.confirm(`Remove the ${provider.label} key? Agents using it will stop until another key is set.`)) return;
    try {
      await api(`/dashboard/providers/${provider.id}`, { method: "DELETE", accountId });
      setNotice(`${provider.label} key removed.`);
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function saveDefaults(event: React.FormEvent) {
    event.preventDefault();
    if (!accountId) return;
    try {
      await api("/dashboard/providers/defaults", {
        method: "PUT",
        accountId,
        body: { provider: defaultProvider || null, model: defaultModel || null },
      });
      setNotice("Default provider saved.");
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  const configured = data?.items.filter((item) => item.configured || item.using_deployment_key) ?? [];

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Connect your own AI provider keys. Their usage is billed by the provider, not by us."
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {notice ? (
        <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)", marginBottom: 14 }}>
          {notice}
        </div>
      ) : null}

      <form className="card" onSubmit={saveDefaults} style={{ marginBottom: 14 }}>
        <div className="card-title">Default model</div>
        <div className="card-sub">
          Used by agents that don&apos;t pin their own provider/model. Per-agent overrides live on Automations.
        </div>
        <div className="two-col" style={{ marginTop: 12 }}>
          <label className="field">
            <span>Provider</span>
            <select value={defaultProvider} onChange={(event) => { setDefaultProvider(event.target.value); setDefaultModel(""); }}>
              <option value="">No default (offline echo)</option>
              {(data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                  {item.configured ? "" : item.using_deployment_key ? " (deployment key)" : " (no key)"}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Model</span>
            <select value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)}>
              <option value="">Provider default</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
          <button className="btn sm" type="submit">
            <Check /> Save default
          </button>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          {configured.length
            ? `${configured.length} provider(s) available for agents: ${configured.map((item) => item.label).join(", ")}.`
            : "No provider configured yet — agents fall back to the offline echo provider."}
        </div>
      </form>

      {(data?.items ?? []).map((provider) => (
        <div className="card" key={provider.id} style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="item-title" style={{ fontSize: 14.5 }}>
                {provider.label}
                {provider.configured ? (
                  <Pill tone="ok">connected</Pill>
                ) : provider.using_deployment_key ? (
                  <Pill tone="warn">deployment key</Pill>
                ) : provider.status === "invalid" ? (
                  <Pill tone="bad">invalid key</Pill>
                ) : (
                  <Pill>not configured</Pill>
                )}
                {provider.is_default ? <Pill>default</Pill> : null}
              </div>
              <div className="row-sub">{provider.description}</div>
              {provider.key_hint ? <div className="row-sub">key {provider.key_hint}</div> : null}
            </div>
            <a className="btn ghost sm" href={provider.docs} target="_blank" rel="noreferrer">
              Get a key <ExternalLink />
            </a>
          </div>

          <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <input
              type="password"
              autoComplete="off"
              placeholder={provider.configured ? "replace key…" : "paste your API key"}
              value={keys[provider.id] ?? ""}
              onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))}
              style={{ flex: 1, minWidth: 240 }}
            />
            <button className="btn sm" onClick={() => saveKey(provider)} disabled={busy === provider.id}>
              <KeyRound /> {busy === provider.id ? "Checking…" : "Save key"}
            </button>
            {provider.configured ? (
              <>
                <button className="btn ghost sm" onClick={() => testKey(provider)} disabled={busy === provider.id}>
                  Test
                </button>
                <button className="btn ghost sm" onClick={() => removeKey(provider)}>
                  <Trash2 />
                </button>
              </>
            ) : null}
          </div>
          <div className="muted" style={{ marginTop: 8, fontSize: 11.5 }}>
            Stored encrypted (AES-GCM). We only keep the last 4 characters for display; the key is never returned by the
            API or sent to the model.
          </div>
        </div>
      ))}
    </>
  );
}
