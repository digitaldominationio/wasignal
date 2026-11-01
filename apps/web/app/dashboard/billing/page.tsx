"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, CreditCard, Plus, TriangleAlert } from "lucide-react";

import { ApiError, BillingStatus, Plan, api } from "@/lib/api";
import { PageHeader, Pill } from "@/components/ui";
import { dateTime, inr } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace";

export default function BillingPage() {
  const { accountId } = useWorkspace();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const [planData, statusData] = await Promise.all([
        api<{ items: Plan[] }>("/dashboard/billing/plans", { accountId }),
        api<BillingStatus>("/dashboard/billing/status", { accountId }),
      ]);
      setPlans(planData.items);
      setStatus(statusData);
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  const canManageBilling = status?.role === "owner" || status?.role === "admin";
  const canAddNumber = canManageBilling || status?.role === "manager";

  async function choose(plan: Plan) {
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      await api("/dashboard/billing/checkout", { method: "POST", accountId, body: { plan_id: plan.id } });
      setNotice(`${plan.name} activated. This scaffold uses a mock provider — wire Stripe/Dodo for real charges.`);
      await load();
    } catch (cause) {
      const err = cause as ApiError;
      setError(
        err.status === 409
          ? "That plan is smaller than your current usage. Remove numbers or members first."
          : err.detail,
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancelRenewal() {
    if (!accountId) return;
    try {
      await api("/dashboard/billing/cancel", { method: "POST", accountId });
      setNotice("Renewal cancelled — the plan runs to the end of the period.");
      await load();
    } catch (cause) {
      setError((cause as ApiError).detail);
    }
  }

  async function addNumber() {
    if (!accountId) return;
    try {
      await api("/dashboard/accounts", { method: "POST", accountId, body: { name: `Number ${(status?.usage.numbers ?? 0) + 1}` } });
      setNotice("Number added. Link it from Connections.");
      await load();
    } catch (cause) {
      const err = cause as ApiError;
      setError(err.status === 402 ? "Your plan has no room for another number." : err.detail);
    }
  }

  const usage = status?.usage;
  const limits = status?.limits;

  return (
    <>
      <PageHeader
        title="Billing"
        subtitle="Plans are per organization. Usage resets with the billing period."
        action={
          canAddNumber ? (
            <button className="btn ghost" onClick={addNumber}>
              <Plus /> Add number
            </button>
          ) : null
        }
      />

      {error ? <div className="card" style={{ borderColor: "#f0cfcc", marginBottom: 14 }}>{error}</div> : null}
      {notice ? (
        <div className="card" style={{ borderColor: "var(--ok-line)", background: "var(--ok-bg)", marginBottom: 14 }}>
          {notice}
        </div>
      ) : null}

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="card-title">
              {status?.plan.name ?? "Current plan"}{" "}
              {status ? <Pill tone={status.subscription.status === "active" ? "ok" : "warn"}>{status.subscription.status}</Pill> : null}
            </div>
            <div className="card-sub">
              {status
                ? `${status.organization} · renews ${dateTime(status.subscription.current_period_end)}`
                : "Loading…"}
              {status?.subscription.cancel_at_period_end ? " · cancellation scheduled" : ""}
            </div>
          </div>
          {canManageBilling && status && !status.subscription.cancel_at_period_end ? (
            <button className="btn ghost sm" onClick={cancelRenewal}>
              Cancel renewal
            </button>
          ) : null}
        </div>

        {status?.exhausted.length ? (
          <div className="row" style={{ gap: 8, marginTop: 12, color: "var(--warn)" }}>
            <TriangleAlert style={{ width: 15, height: 15 }} />
            <span className="muted">
              You&apos;ve hit the {status.exhausted.join(", ")} limit on this plan. New replies are paused until you
              upgrade or the period resets.
            </span>
          </div>
        ) : null}

        <div className="divider" />

        <div className="card-sub" style={{ marginBottom: 10 }}>
          Usage this period
        </div>
        <div style={{ display: "grid", gap: 12 }}>
          <UsageBar label="Messages this period" used={usage?.messages ?? 0} limit={limits?.messages ?? 0} />
          <UsageBar label="Numbers" used={usage?.numbers ?? 0} limit={limits?.numbers ?? 0} />
          <UsageBar label="Seats" used={usage?.seats ?? 0} limit={limits?.seats ?? 0} />
        </div>
      </div>

      <div className="card">
        <div className="card-title">Plans</div>
        <div className="card-sub">Switch anytime. A downgrade must fit your current numbers and seats.</div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 12, marginTop: 14 }}>
          {plans.map((plan) => {
            const current = status?.plan.id === plan.id;
            return (
              <div
                key={plan.id}
                className="card"
                style={{
                  borderColor: plan.recommended ? "var(--ink)" : "var(--line)",
                  boxShadow: plan.recommended ? "0 0 0 1px var(--ink)" : undefined,
                }}
              >
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div className="card-title">{plan.name}</div>
                  {current ? <Pill tone="ok">current</Pill> : plan.recommended ? <Pill>popular</Pill> : null}
                </div>
                <div className="muted" style={{ marginTop: 2 }}>
                  {plan.tagline}
                </div>
                <div style={{ fontSize: 22, fontWeight: 650, margin: "10px 0 2px" }}>
                  {plan.price_inr === 0 ? "Free" : inr(plan.price_inr)}
                </div>
                <div className="muted">{plan.period}</div>

                <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 8px", display: "grid", gap: 6 }}>
                  {plan.features.map((feature) => (
                    <li key={feature} className="row" style={{ gap: 7, fontSize: 12.5 }}>
                      <Check style={{ width: 13, height: 13, color: "var(--ok)" }} />
                      {feature}
                    </li>
                  ))}
                </ul>

                <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>
                  {plan.limits.numbers} numbers · {plan.limits.seats} seats ·{" "}
                  {plan.limits.messages.toLocaleString("en-IN")} messages
                </div>

                <button
                  className={plan.recommended && !current ? "btn" : "btn ghost"}
                  style={{ width: "100%" }}
                  disabled={current || busy || !canManageBilling}
                  onClick={() => choose(plan)}
                  title={!canManageBilling ? "Only admins can change the plan" : undefined}
                >
                  <CreditCard /> {current ? "Current plan" : `Choose ${plan.name}`}
                </button>
              </div>
            );
          })}
        </div>

        {!canManageBilling ? (
          <p className="muted" style={{ marginTop: 12 }}>
            Only an owner or admin can change the plan.
          </p>
        ) : (
          <p className="muted" style={{ marginTop: 12 }}>
            Checkout is mocked in this scaffold: choosing a plan writes a subscription row with provider{" "}
            <code>manual</code>. Replace it with a Stripe/Dodo session and let <code>/webhook/stripe</code> apply the
            result.
          </p>
        )}
      </div>
    </>
  );
}

function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="quota-head">
        <span>{label}</span>
        <span>
          {used.toLocaleString("en-IN")} / {limit.toLocaleString("en-IN")}
        </span>
      </div>
      <div className="quota-bar" style={{ margin: "6px 0 0" }}>
        <span style={{ width: `${percent}%`, background: percent >= 100 ? "var(--danger)" : undefined }} />
      </div>
    </div>
  );
}
