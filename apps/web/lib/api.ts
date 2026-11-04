export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`API ${status}`);
    this.status = status;
    this.body = body;
  }

  get detail(): string {
    const body = this.body as { detail?: unknown } | null;
    if (!body || body.detail === undefined) return `Request failed (${this.status})`;
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail);
  }
}

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "ws_token";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private mode */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

type ApiOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  accountId?: number | null;
};

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, accountId, headers, ...rest } = options;
  // Split deployment: talk to the API host directly. Same-origin dev: /api proxy.
  const url = new URL(`${API_BASE}${API_BASE ? "" : "/api"}${path}`, window.location.origin);
  if (accountId && path.startsWith("/dashboard") && !path.startsWith("/dashboard/auth")) {
    url.searchParams.set("account_pid", String(accountId));
  }

  const token = getStoredToken();
  const response = await fetch(url.toString(), {
    ...rest,
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "content-type": "application/json" } : {}),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (response.status === 401 && token) {
    clearToken();
  }
  if (!response.ok) {
    throw new ApiError(response.status, payload);
  }
  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 300) };
  }
}

export type Account = { id: number; name: string; wa_number: string; timezone: string; subscription_status: string };

export type Agent = {
  id: number;
  name: string;
  status: "active" | "paused";
  trigger_type: string;
  trigger_scope: string;
  trigger_condition: string | null;
  room_id: number | null;
  chat_type: string;
  capabilities: string[];
  system_prompt: string;
  llm_provider: string | null;
  llm_model: string | null;
};

export type ModelInfo = {
  id: string;
  name: string;
  context_length: number;
  prompt_usd_per_mtok: number;
  completion_usd_per_mtok: number;
  free: boolean;
  multimodal: boolean;
};

export type Room = {
  id: number;
  display_name: string;
  kind: "dm" | "group" | "system";
  is_excluded: number;
  external_id: string;
  last_activity_at: number;
};

export type Message = {
  id: number;
  direction: "in" | "out";
  text: string;
  ts: number;
  status: string;
  sender_name: string;
  source: string;
  media?: { type?: string; name?: string; url?: string | null }[];
};

export type SendResult = {
  accepted: boolean;
  stage: string;
  reply: string;
  delivery: string;
  run_id: number | null;
};

export type Plan = {
  id: string;
  name: string;
  price_inr: number;
  period: string;
  tagline: string;
  features: string[];
  limits: { numbers: number; seats: number; messages: number };
  lookup_key: string;
  recommended: boolean;
};

export type BillingStatus = {
  org_id: number;
  organization: string;
  role: string;
  plan: Plan;
  subscription: {
    status: string;
    provider: string;
    current_period_start: number;
    current_period_end: number;
    cancel_at_period_end: boolean;
  };
  limits: { numbers: number; seats: number; messages: number };
  usage: { messages: number; runs: number; numbers: number; seats: number };
  remaining: Record<string, number>;
  over: string[];
  exhausted: string[];
};

export type TeamMember = { pid: number; name: string; phone: string; role: string; is_owner: boolean };
export type TeamInvitation = {
  id: number;
  phone: string;
  role: string;
  token: string;
  created_at: number;
  expires_at: number;
};
export type TeamPayload = {
  organization: { id: number; name: string; slug: string };
  role: string;
  plan: string;
  status: string;
  members: TeamMember[];
  invitations: TeamInvitation[];
  seats: { used: number; pending: number; limit: number };
};
export type OrgSummary = {
  id: number;
  name: string;
  slug: string;
  role: string;
  plan: string;
  status: string;
  numbers: number;
  seats: number;
};

export type ProviderInfo = {
  id: string;
  label: string;
  description: string;
  docs: string;
  configured: boolean;
  key_hint: string | null;
  status: "active" | "invalid" | "unconfigured" | "deployment" | "revoked";
  base_url: string | null;
  default_model: string;
  using_deployment_key: boolean;
  is_default: boolean;
};

export type ProvidersResponse = {
  items: ProviderInfo[];
  default_provider: string | null;
  default_model: string | null;
};
