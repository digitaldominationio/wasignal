# Deployment

Two artifacts, two hosts:

```
apps/web  → Cloudflare Pages (static export) or Workers (OpenNext)
apps/api  → your VPS / container host, behind Caddy or a Cloudflare Tunnel
```

They are already separated in the repo. What the split needs is transport
configuration: where the browser sends API calls, which origins may call the
API, and how the session travels.

---

## 1. Pick an auth topology first

This decides everything else.

| Topology | Frontend origin | API origin | Auth | Cookies work? |
|---|---|---|---|---|
| **A. Same-site subdomains** *(recommended)* | `https://app.wasignal.com` | `https://api.wasignal.com` | cookie + `SameSite=Lax` | Yes — same registrable domain |
| **B. Truly cross-site** | `https://wasignal.pages.dev` | `https://api.wasignal.com` | Bearer token | No — browsers drop `SameSite=Lax` on cross-site fetch |
| **C. Same-origin proxy** (current dev default) | `http://localhost:3000` | proxied through Next | cookie | Yes |

The web client supports all three without code changes:

- `NEXT_PUBLIC_API_BASE_URL` unset → calls `/api` on its own origin (topology C).
- `NEXT_PUBLIC_API_BASE_URL=https://api.example.com` → calls the API directly.
- The login response always includes `access_token`; the client stores it and
  sends `Authorization: Bearer …`, so topologies A and B both work even if
  cookies are unavailable.

> Cloudflare **preview** deployments (`*.pages.dev`) are always topology B.
> Production on a custom domain under the same parent is topology A.

---

## 2. Backend on your server

### Option 1 — Docker Compose

```bash
cd deploy
cp ../.env ../.env            # then edit for production
docker compose up -d --build
curl -s http://127.0.0.1:8000/health/ready
```

The compose file binds `127.0.0.1:8000`, so put Caddy (or a tunnel) in front.

### Option 2 — Caddy on the host

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # edit the hostname
sudo systemctl reload caddy
```

Caddy provisions TLS automatically. If the DNS record is proxied by Cloudflare,
set SSL mode to **Full (strict)**.

### Option 3 — Cloudflare Tunnel (no open ports)

```bash
cloudflared tunnel create wasignal
cloudflared tunnel route dns wasignal api.wasignal.com
cloudflared tunnel run --config deploy/cloudflared.yml wasignal
```

### Option 4 — systemd

```bash
sudo useradd -r -s /usr/sbin/nologin wasignal
sudo rsync -a apps/api/ /srv/wasignal/apps/api/
python3.12 -m venv /srv/wasignal/apps/api/.venv
/srv/wasignal/apps/api/.venv/bin/pip install -r /srv/wasignal/apps/api/requirements.txt
sudo cp deploy/wasignal-api.service /etc/systemd/system/
sudo systemctl enable --now wasignal-api
```

### Backend env for a split deployment

```bash
WASIGNAL_ENV=production
WASIGNAL_DATA_DIR=/data

# who may call the API from a browser
WASIGNAL_CORS_ORIGINS=https://app.wasignal.com

# share the session cookie with the web subdomain (topology A)
WASIGNAL_COOKIE_DOMAIN=.wasignal.com
WASIGNAL_COOKIE_SECURE=true
WASIGNAL_COOKIE_SAMESITE=lax

OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o-mini
WASIGNAL_INTERNAL_KEY=<long random string>
```

For topology B (pages.dev) omit `WASIGNAL_COOKIE_DOMAIN`; the client falls back
to the Bearer token automatically.

CORS must list exact origins — never `*`, because `allow_credentials=True`.

---

## 3. Frontend on Cloudflare

### Static export (Pages) — fastest, zero adapter

```bash
cd apps/web
NEXT_PUBLIC_API_BASE_URL=https://api.wasignal.com npm run build:static
# deploy the out/ directory
```

The static build excludes the Next API proxy (`app/api/[...path]/route.proxy.ts`
is only compiled in server builds) and inlines `NEXT_PUBLIC_API_BASE_URL`.

Cloudflare Pages settings:

| Setting | Value |
|---|---|
| Root directory | `apps/web` |
| Framework preset | Next.js (Static HTML Export) |
| Build command | `npm run build:static` |
| Output directory | `out` |
| Node version | `22` (env `NODE_VERSION=22`) |
| Env var | `NEXT_PUBLIC_API_BASE_URL=https://api.wasignal.com` |

Add the custom domain `app.wasignal.com` under **Custom domains** so cookies
work (topology A). Preview URLs will use the Bearer path (topology B).

Direct upload also works:

```bash
npx wrangler pages deploy out --project-name wasignal
```

### Workers (OpenNext) — when you want to keep the proxy / SSR

If you'd rather keep the same-origin `/api` proxy (topology C on Cloudflare):

```bash
cd apps/web
npx @opennextjs/cloudflare build
npx wrangler deploy
```

Trade-off: every API call passes through a Worker — one more hop, one more
place to debug — in exchange for same-origin cookies. For this app the static
export is simpler and faster; use Workers only if you add server-only features.

---

## 4. Verify the split

```bash
# API is reachable from the internet and allows the web origin
curl -s https://api.wasignal.com/health/ready
curl -si -X OPTIONS https://api.wasignal.com/dashboard/agents \
  -H 'Origin: https://app.wasignal.com' \
  -H 'Access-Control-Request-Method: GET' \
  | grep -i 'access-control'

# login + bearer works without cookies
TOKEN=$(curl -s -X POST https://api.wasignal.com/dashboard/auth/request-otp \
  -H 'content-type: application/json' -d '{"phone":"9999000001"}' >/dev/null; \
  curl -s -X POST https://api.wasignal.com/dashboard/auth/verify-otp \
  -H 'content-type: application/json' \
  -d '{"phone":"9999000001","otp":"123456"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s https://api.wasignal.com/dashboard/agents -H "Authorization: Bearer $TOKEN"
```

Then open the Pages URL, sign in, and confirm the network tab shows requests to
`api.wasignal.com` with an `Origin` header and (on the custom domain) a
`ws_session` cookie.

---

## 5. What "faster development" actually means here

What genuinely gets faster:

- Frontend deploys are static uploads (~10s) and need no server restart.
- Backend changes deploy independently; no rebuild of the UI.
- Cloudflare preview URLs per branch for the UI; the API keeps its state.
- One repo still: shared types live in `apps/web/lib/api.ts`, the contract is
  `/openapi.json`.

What gets slower if you're not careful:

- **CORS + cookie debugging** — pick topology A and keep the same parent domain.
- **Two env sets** — keep `.env` for the API and Cloudflare env vars for the web;
  this doc is the map.
- **Cold starts** if you add Workers/OpenNext — the static export avoids them.

---

## 6. Before you scale

The API is deliberately single-instance:

- SQLite (`apps/api/data/wasignal.db`) — one writer.
- In-process outbox worker and scheduler — more replicas means duplicate sends.

To scale, in this order:

1. Move the store to Postgres/Mongo (`repo.py` is the only SQL surface).
2. Move the outbox + ticker to a separate worker process (or Celery/RQ/Cloud
   Tasks) and run the API stateless behind a load balancer.
3. Add Redis for cross-process caches (model catalogue, human-pause TTL).
4. Then and only then run multiple API replicas.

## 7. Security checklist

- [ ] `WASIGNAL_ENV=production` (OTP is no longer returned in the response)
- [ ] `WASIGNAL_INTERNAL_KEY` random, long, and `/internal/*` not publicly exposed
- [ ] CORS lists exact origins; no `*` with credentials
- [ ] `WASIGNAL_COOKIE_SECURE=true` and HTTPS everywhere
- [ ] Cloudflare SSL mode Full (strict) if the record is proxied
- [ ] `apps/api/data/` backed up (it holds sessions, messages, runs)
- [ ] rate limit `/dashboard/auth/request-otp` at the edge or in Caddy
- [ ] rotate the OpenRouter key if it ever lands in a log
