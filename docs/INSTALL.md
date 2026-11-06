# Install on a VPS

One command on a fresh Debian/Ubuntu server:

```bash
curl -fsSL https://raw.githubusercontent.com/digitaldominationio/wasignal/main/install.sh | sudo bash
```

The installer asks for a domain (optional) and an admin phone, then does everything:

- installs Docker + Compose
- adds 2 GB swap on small servers
- generates MongoDB and Redis passwords, the encryption key and the internal key
- runs the app, MongoDB and Redis with health checks
- fronts it with Caddy (automatic HTTPS when a domain is given)
- seeds one workspace and makes the admin phone a superadmin
- schedules a nightly MongoDB backup

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Debian 12 / Ubuntu 22.04+ | Ubuntu 24.04 |
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB (2 GB swap added automatically) | 2 GB |
| Disk | 10 GB | 20 GB |
| Ports | 22, 80, 443 open | |

Works on amd64 and arm64. Root access is required.

## Options

Pass them through `sudo` (env is not preserved by plain `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/digitaldominationio/wasignal/main/install.sh \
  | sudo DOMAIN=app.example.com ADMIN_PHONE=919999000001 bash
```

| Variable | Meaning | Default |
|---|---|---|
| `DOMAIN` | public hostname; blank = serve on the server IP over HTTP | blank |
| `ADMIN_PHONE` | first login + superadmin phone (digits) | `9999000001` |
| `ADMIN_OTP` | fixed login OTP for bootstrap | random, printed at the end |
| `WASIGNAL_DIR` | install directory | `/opt/wasignal` |
| `WASIGNAL_IMAGE` | container image | `ghcr.io/digitaldominationio/wasignal:latest` |

If the image cannot be pulled (private registry or offline), the installer clones
the repo and builds it locally — slower, and it needs the swap it just created.

## After install

The summary prints:

```
URL     https://app.example.com
Login   phone 919999000001
OTP     482913
Admin   https://app.example.com/dashboard/admin
```

Point the DNS **A record** at the server before or after; Caddy keeps retrying
the certificate until it succeeds.

Change the OTP once you have real OTP delivery:

```bash
sudo nano /opt/wasignal/.env     # WASIGNAL_DEV_OTP=
cd /opt/wasignal && sudo docker compose up -d
```

> The bootstrap OTP is fixed because this build has no WhatsApp/email OTP
> delivery yet. Anyone with the phone number and that OTP can sign in. Replace it
> with a random value and keep it private until the bridge is wired.

## Day-to-day

```bash
cd /opt/wasignal

sudo ./install.sh status     # containers + health
sudo ./install.sh logs       # follow API logs
sudo ./install.sh update     # pull the new image and restart
sudo ./install.sh backup     # mongodump to /var/backups/wasignal
sudo ./install.sh uninstall  # stop (keeps data)
sudo ./install.sh uninstall --purge   # stop and delete volumes + directory
```

Backups run nightly at 02:30 and keep 7 days.

### Restore

```bash
cd /opt/wasignal
sudo docker compose exec -T mongo mongorestore --archive --gzip \
  --username wasignal --password "$(grep '^MONGO_PASSWORD=' .env | cut -d= -f2)" \
  --authenticationDatabase admin < /var/backups/wasignal/mongo-YYYYmmdd-HHMMSS.gz
sudo docker compose restart app
```

## What you get

- API + dashboard on one origin (`/api/*` proxied internally)
- MongoDB with auth, Redis with a password, no database ports published
- Secrets in `/opt/wasignal/.env` (mode 600), keys encrypted at rest with
  `WASIGNAL_SECRET_KEY` — **back this file up**; losing it makes tenant LLM and
  Composio keys undecryptable
- Superadmin impersonation at `/dashboard/admin`; every impersonated write is audit-logged

## Troubleshooting

```bash
cd /opt/wasignal
sudo docker compose ps
sudo docker compose logs --tail=100 app
sudo docker compose logs --tail=50 mongo
```

| Symptom | Fix |
|---|---|
| 502 from Caddy | API still starting; `docker compose logs app` |
| Certificate not issued | DNS not pointing here yet, or 80/443 blocked |
| Mongo exited | low memory — confirm swap is on (`swapon --show`) |
| Login fails on IP-only install | cookie must not be `Secure`; the installer sets `WASIGNAL_COOKIE_SECURE=false` in that mode |
| Need a clean slate | `./install.sh uninstall --purge` then reinstall |
