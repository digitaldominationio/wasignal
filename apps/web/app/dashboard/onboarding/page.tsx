"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, MessageCircle, QrCode, ShieldCheck } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

type Onboarding = {
  whatsapp: {
    connected: boolean;
    channel: string | null;
    methods: { id: string; label: string; description: string; available: boolean }[];
  };
  google: { calendar: boolean; gmail: boolean; broker_configured: boolean };
  complete: boolean;
};

export default function OnboardingPage() {
  const router = useRouter();
  const { accountId } = useWorkspace();
  const [data, setData] = useState<Onboarding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [linkState, setLinkState] = useState("pending");
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      setData(await api<Onboarding>("/dashboard/onboarding", { accountId }));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  async function connectQr() {
    if (!accountId) return;
    setError(null);
    try {
      const started = await api<{ state: string; qr_image_base64?: string }>(
        "/dashboard/whatsapp/start-link",
        { method: "POST", accountId, body: { login_method: "qr" } },
      );
      setQr(started.qr_image_base64 ?? null);
      setLinkState(started.state ?? "pending");
      setQrOpen(true);
      if (poll.current) clearInterval(poll.current);
      poll.current = setInterval(async () => {
        try {
          const status = await api<{ state: string; qr_image_base64?: string }>(
            "/dashboard/whatsapp/link-status",
            { accountId },
          );
          setLinkState(status.state);
          if (status.qr_image_base64) setQr(status.qr_image_base64);
          if (status.state === "connected") {
            if (poll.current) clearInterval(poll.current);
            setQrOpen(false);
            setNotice("WhatsApp connected.");
            await load();
          }
        } catch {
          if (poll.current) clearInterval(poll.current);
        }
      }, 1500);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function connectGoogle(service: "google_calendar" | "gmail") {
    if (!accountId) return;
    setError(null);
    try {
      const result = await api<{ redirect_url?: string }>(
        `/dashboard/integrations/${service}/connect`,
        { method: "POST", accountId },
      );
      if (result.redirect_url) {
        window.location.href = result.redirect_url;
        return;
      }
      throw new Error("no redirect");
    } catch (cause) {
      const err = cause as ApiError;
      setError(
        err.status === 409
          ? "The integration broker isn't configured on this deployment yet (COMPOSIO_API_KEY)."
          : err.detail,
      );
    }
  }

  const whatsapp = data?.whatsapp;
  const qrMethod = whatsapp?.methods.find((method) => method.id === "qr");
  const official = whatsapp?.methods.find((method) => method.id === "official");

  return (
    <>
      <PageHeader
        title="Set up your workspace"
        subtitle="Two steps: connect WhatsApp, then let the agent act in your Google account."
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {notice ? <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)", marginBottom: 14 }}>{notice}</div> : null}

      <div className="card" style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="avatar" style={{ width: 30, height: 30, fontSize: 12 }}>
            1
          </span>
          <div style={{ flex: 1 }}>
            <div className="card-title">Connect WhatsApp</div>
            <div className="card-sub">The agent answers and follows up on this number.</div>
          </div>
          {whatsapp?.connected ? <Pill tone="ok">connected</Pill> : <Pill tone="warn">required</Pill>}
        </div>

        {whatsapp?.connected ? (
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <Check style={{ width: 15, height: 15, color: "var(--ok)" }} />
            <span className="muted">WhatsApp is linked ({whatsapp.channel ?? "bridge"}).</span>
          </div>
        ) : (
          <div className="item-row" style={{ marginTop: 12 }}>
            <span className="item-icon">
              <QrCode />
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="item-title">
                {qrMethod?.label ?? "Scan a QR code"}
                <Pill tone="ok">two-way</Pill>
              </div>
              <div className="row-sub">{qrMethod?.description}</div>
            </div>
            <div className="row-action">
              <button className="btn sm" onClick={connectQr}>
                Connect
              </button>
            </div>
          </div>
        )}

        <div className="item-row" style={{ opacity: official?.available ? 1 : 0.65 }}>
          <span className="item-icon">
            <MessageCircle />
          </span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="item-title">
              WhatsApp Business (official)
              {official?.available ? <Pill tone="ok">available</Pill> : <Pill>needs Meta app</Pill>}
            </div>
            <div className="row-sub">{official?.description}</div>
          </div>
          <div className="row-action">
            <button className="btn ghost sm" disabled title="Requires a Meta app + WABA webhook">
              Official
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="avatar" style={{ width: 30, height: 30, fontSize: 12 }}>
            2
          </span>
          <div style={{ flex: 1 }}>
            <div className="card-title">Let it act in Google</div>
            <div className="card-sub">Calendar and Gmail are connected through Composio — no Google verification wait.</div>
          </div>
          <Pill tone={data?.google.calendar && data?.google.gmail ? "ok" : undefined}>
            {data?.google.calendar || data?.google.gmail ? "partly connected" : "optional"}
          </Pill>
        </div>

        {!data?.google.broker_configured ? (
          <div className="muted" style={{ marginTop: 10 }}>
            The broker isn&apos;t configured yet. Add <code>COMPOSIO_API_KEY</code> and the Google auth-config ids,
            then reload.
          </div>
        ) : null}

        {[
          { id: "google_calendar" as const, label: "Google Calendar", connected: data?.google.calendar, detail: "Find slots and book events" },
          { id: "gmail" as const, label: "Gmail", connected: data?.google.gmail, detail: "Search mail, draft and send replies" },
        ].map((service) => (
          <div className="item-row" key={service.id}>
            <span className="item-icon">
              <ShieldCheck />
            </span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="item-title">
                {service.label}
                {service.connected ? <Pill tone="ok">connected</Pill> : <Pill>not connected</Pill>}
              </div>
              <div className="row-sub">{service.connected ? "Ready for the agent" : service.detail}</div>
            </div>
            <div className="row-action">
              {service.connected ? (
                <button className="btn ghost sm" onClick={() => router.push("/dashboard/connections")}>
                  Manage
                </button>
              ) : (
                <button
                  className="btn sm"
                  onClick={() => connectGoogle(service.id)}
                  disabled={!data?.google.broker_configured}
                >
                  Connect
                </button>
              )}
            </div>
          </div>
        ))}

        <div className="divider" />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="btn ghost" onClick={() => router.push("/dashboard/connections")}>
            All connections
          </button>
          <button className="btn" onClick={() => router.push("/dashboard")}>
            Continue <ArrowRight />
          </button>
        </div>
      </div>

      {qrOpen ? (
        <div className="modal-backdrop" onMouseDown={() => setQrOpen(false)}>
          <div className="modal" style={{ width: 400 }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h3>Link WhatsApp</h3>
              <button className="btn ghost sm" onClick={() => setQrOpen(false)} aria-label="Close">
                ×
              </button>
            </div>
            <p className="muted">
              On your phone: WhatsApp → Settings → Linked devices → Link a device.
            </p>
            <div className="qr">
              {qr ? <img src={`data:image/png;base64,${qr}`} alt="WhatsApp QR" /> : <span className="muted">Waiting…</span>}
            </div>
            <div className="row" style={{ justifyContent: "center" }}>
              <Pill tone={linkState === "pending" ? "warn" : undefined}>{linkState}</Pill>
            </div>
            <p className="muted" style={{ textAlign: "center", marginTop: 8 }}>
              Demo deployments use a stub bridge — the QR is a placeholder and flips to connected after a few seconds.
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
