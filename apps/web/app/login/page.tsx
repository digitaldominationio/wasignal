"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, MessageCircle } from "lucide-react";

import { ApiError, api, storeToken } from "@/lib/api";

type Mode = "login" | "signup";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [phone, setPhone] = useState("9999000001");
  const [name, setName] = useState("");
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [otp, setOtp] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function requestOtp(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result =
        mode === "signup"
          ? await api<{ status: string; dev_code?: string }>("/dashboard/auth/signup", {
              method: "POST",
              body: { name, phone },
            })
          : await api<{ status: string; dev_code?: string }>("/dashboard/auth/request-otp", {
              method: "POST",
              body: { phone },
            });
      setDevCode(result.dev_code ?? null);
      setStep("otp");
    } catch (cause) {
      const err = cause as ApiError;
      setError(
        err.status === 404
          ? "That number has no account yet. Create one instead."
          : err.status === 409
            ? "That number already has an account — sign in."
            : err.detail,
      );
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api<{ access_token?: string }>("/dashboard/auth/verify-otp", {
        method: "POST",
        body: { phone, otp },
      });
      if (session.access_token) storeToken(session.access_token);
      router.replace("/dashboard");
    } catch (cause) {
      setError((cause as ApiError).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth">
        <div className="auth-mark">
          <span className="brand-mark">W</span>
          wasignal
        </div>

        {step === "phone" ? (
          <form className="auth-card" onSubmit={requestOtp}>
            <div>
              <h1>{mode === "login" ? "Sign in" : "Create your workspace"}</h1>
              <p className="muted" style={{ marginTop: 6 }}>
                {mode === "login"
                  ? "We send a 6-digit code over WhatsApp — the same channel your agent lives on."
                  : "One number, one agent. Add more numbers once you're in."}
              </p>
            </div>

            {mode === "signup" ? (
              <label className="field">
                <span>Your name</span>
                <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ambition Academy" required />
              </label>
            ) : null}

            <label className="field">
              <span>WhatsApp number</span>
              <input value={phone} onChange={(event) => setPhone(event.target.value)} inputMode="tel" placeholder="9999000001" required />
            </label>

            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Sending…" : <>Send code <ArrowRight /></>}
            </button>

            <button
              type="button"
              className="btn ghost"
              onClick={() => {
                setMode(mode === "login" ? "signup" : "login");
                setError(null);
              }}
            >
              {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
            </button>

            {error ? <p className="error">{error}</p> : null}
          </form>
        ) : (
          <form className="auth-card" onSubmit={verifyOtp}>
            <div>
              <h1>Enter the code</h1>
              <p className="muted" style={{ marginTop: 6 }}>
                Sent to {phone}. In development the code is shown on this page instead of WhatsApp.
              </p>
            </div>

            {devCode ? <span className="pill warn">dev code: {devCode}</span> : null}

            <label className="field">
              <span>6-digit code</span>
              <input
                value={otp}
                onChange={(event) => setOtp(event.target.value)}
                inputMode="numeric"
                placeholder="123456"
                maxLength={6}
                autoFocus
                required
              />
            </label>

            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Checking…" : "Verify and continue"}
            </button>
            <button type="button" className="btn ghost" onClick={() => setStep("phone")}>
              Use a different number
            </button>

            {error ? <p className="error">{error}</p> : null}
          </form>
        )}

        <div className="card" style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
          <MessageCircle style={{ width: 16, height: 16, marginTop: 2, color: "var(--ok)" }} />
          <div className="muted">
            Demo workspace <code>9999000001</code> — admissions agent, fee knowledge base and three chats, seeded on
            first boot.
          </div>
        </div>
      </div>
    </div>
  );
}
