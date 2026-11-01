"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Briefcase,
  CalendarDays,
  FileText,
  HardDrive,
  Hash,
  Mail,
  MessageCircle,
  Sheet,
  TriangleAlert,
  X,
} from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { useWorkspace } from "@/lib/workspace";

type ConnectionItem = {
  id: string;
  label: string;
  description: string;
  connected: boolean;
  detail: string;
  required?: boolean;
};

type ConnectionsResponse = {
  whatsapp: ConnectionItem;
  groups: { group: string; hint: string; items: ConnectionItem[] }[];
};

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  gmail: Mail,
  google_calendar: CalendarDays,
  google_sheets: Sheet,
  google_drive: HardDrive,
  notion: FileText,
  slack: Hash,
  hubspot: Briefcase,
};

export default function ConnectionsPage() {
  const { accountId } = useWorkspace();
  const [data, setData] = useState<ConnectionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [linkState, setLinkState] = useState("pending");
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      setData(await api<ConnectionsResponse>("/dashboard/connections", { accountId }));
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  const stopPolling = useCallback(() => {
    if (poll.current) {
      clearInterval(poll.current);
      poll.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function connectWhatsApp() {
    if (!accountId) return;
    setError(null);
    try {
      const started = await api<{ state: string; qr_image_base64?: string }>(
        "/dashboard/connections/whatsapp/connect",
        { method: "POST", accountId },
      );
      setQr(started.qr_image_base64 ?? null);
      setLinkState(started.state ?? "pending");
      setQrOpen(true);
      stopPolling();
      poll.current = setInterval(async () => {
        try {
          const status = await api<{ state: string; qr_image_base64?: string }>(
            "/dashboard/whatsapp/link-status",
            { accountId },
          );
          setLinkState(status.state);
          if (status.qr_image_base64) setQr(status.qr_image_base64);
          if (status.state === "connected") {
            stopPolling();
            setQrOpen(false);
            await load();
          }
        } catch {
          stopPolling();
        }
      }, 1500);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function disconnect(service: string) {
    if (!accountId) return;
    try {
      await api(`/dashboard/connections/${service}`, { method: "DELETE", accountId });
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function connectOther(service: string) {
    if (!accountId) return;
    setNote(null);
    try {
      await api(`/dashboard/connections/${service}/connect`, { method: "POST", accountId });
      await load();
    } catch (cause) {
      const err = cause as ApiError;
      setNote(
        err.detail === "oauth_not_configured"
          ? "OAuth isn't configured on this deployment yet. Add the provider credentials to enable this connection."
          : err.detail,
      );
    }
  }

  const whatsapp = data?.whatsapp;

  return (
    <>
      <PageHeader
        title="Connections"
        subtitle="Connect apps to let your automations use them."
        action={
          whatsapp && !whatsapp.connected ? (
            <button className="btn" onClick={connectWhatsApp}>
              Connect WhatsApp
            </button>
          ) : null
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {note ? <div className="card" style={{ borderColor: "#f1e0b8", background: "#fffdf4", marginBottom: 14 }}>{note}</div> : null}

      <div className="group">
        <div className="group-head">
          <div className="card-title">WhatsApp</div>
          <div className="card-sub">Required — automations and scheduled messages won&apos;t work without this.</div>
        </div>

        <div className="item-row required">
          <span className="item-icon">
            <MessageCircle />
          </span>
          <div style={{ minWidth: 0 }}>
            <div className="item-title">
              WhatsApp
              {whatsapp?.connected ? <Pill tone="ok">Connected</Pill> : <Pill>Not connected</Pill>}
            </div>
            <div className="row-sub">{whatsapp?.connected ? whatsapp.detail : "Not connected yet"}</div>
          </div>
          <div className="row-action">
            {whatsapp?.connected ? (
              <button className="btn ghost sm" onClick={() => disconnect("whatsapp")}>
                Disconnect
              </button>
            ) : (
              <button className="btn sm" onClick={connectWhatsApp}>
                Connect
              </button>
            )}
          </div>
        </div>
      </div>

      {(data?.groups ?? []).map((group) => (
        <div className="group" key={group.group}>
          <div className="group-head">
            <div className="card-title">{group.group}</div>
            <div className="card-sub">{group.hint}</div>
          </div>

          {group.items.map((item) => {
            const Icon = ICONS[item.id] ?? Briefcase;
            return (
              <div className="item-row" key={item.id}>
                <span className="item-icon">
                  <Icon />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="item-title">
                    {item.label}
                    {item.connected ? <Pill tone="ok">Connected</Pill> : <Pill>Not connected</Pill>}
                  </div>
                  <div className="row-sub">{item.connected ? item.detail : "Not connected yet"}</div>
                </div>
                <div className="row-action">
                  {item.connected ? (
                    <button className="btn ghost sm" onClick={() => disconnect(item.id)}>
                      Disconnect
                    </button>
                  ) : (
                    <button className="btn sm" onClick={() => connectOther(item.id)}>
                      Connect
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ))}

      {qrOpen ? (
        <div className="modal-backdrop" onMouseDown={() => setQrOpen(false)}>
          <div className="modal" style={{ width: 400 }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h3>Link WhatsApp</h3>
              <button className="btn ghost sm" onClick={() => setQrOpen(false)} aria-label="Close">
                <X />
              </button>
            </div>
            <p className="muted">
              On your phone: WhatsApp → Settings → Linked devices → Link a device. This uses one linked-device slot;
              your WhatsApp keeps working normally.
            </p>
            <div className="qr">
              {qr ? <img src={`data:image/png;base64,${qr}`} alt="WhatsApp QR code" /> : <span className="muted">Waiting for QR…</span>}
            </div>
            <div className="row" style={{ justifyContent: "center", gap: 8 }}>
              <Pill tone={linkState === "pending" ? "warn" : undefined}>{linkState}</Pill>
              {linkState === "expired" || linkState === "failed" ? (
                <button className="btn sm" onClick={connectWhatsApp}>
                  Retry
                </button>
              ) : null}
            </div>
            <p className="muted" style={{ textAlign: "center", marginTop: 10 }}>
              <TriangleAlert style={{ width: 13, height: 13, verticalAlign: -2 }} /> Demo deployments use a stub
              bridge: the QR is a placeholder and the status flips to connected after a few seconds.
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
