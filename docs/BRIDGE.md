# Bridge contract (WhatsApp transport)

The API never talks to WhatsApp. A **bridge** owns one linked-device session per
number and speaks two dialects:

1. **Inbound** — normalised messages posted to `POST /internal/inbound`
2. **Outbound** — messages pulled from the outbox by the channel worker

```
WhatsApp ⇄ bridge (session per number) ⇄ Wasignal API
                │                              │
                │   POST /internal/inbound     │
                │ ───────────────────────────► │
                │   channel.send(account, room)│
                │ ◄─────────────────────────── │
```

## 1. Inbound payload

```http
POST /internal/inbound
x-internal-key: <WASIGNAL_INTERNAL_KEY>

{
  "account_id": 1,
  "external_room_id": "919900000001@s.whatsapp.net",
  "room_kind": "dm",                  // dm | group
  "sender": "919900000001@s.whatsapp.net",
  "sender_name": "Aarav Sharma",
  "text": "kitni fees hai?",
  "media": [{"url": "https://...", "type": "image", "name": "fee.pdf"}],
  "timestamp": 1793542902,
  "is_human_owner": false
}
```

Rules that keep the pipeline honest:

* `external_room_id` is stable per chat; group ids look like `<id>@g.us`.
* `is_human_owner: true` records an **owner** message — that is what arms
  `human_active_pause`. Do not set it for customer messages.
* Media must be an absolute URL the *server* can fetch without cookies (the
  agent pastes URLs into prompts). Re-host or sign them; never hand the model a
  URL that requires the dashboard session.
* Return `202` immediately; never block the webhook on the LLM.

## 2. Outbound

The worker calls `Channel.send(account, room, text, media)`:

| Transport | Implementation |
|---|---|
| stub (default) | prints, returns a synthetic id |
| Meta Cloud API | `POST /{phone_number_id}/messages` (implemented) |
| linked-device bridge | your bridge's send endpoint |

Message **idempotency**: the worker marks `outbox.status='sent'` *after* the
transport call. A crash in between re-sends. Either pass an idempotency key the
bridge dedupes (`outbox.id` is a good one) or record sends before the call and
reconcile.

## 3. Link lifecycle

```
POST /dashboard/whatsapp/start-link {login_method: "qr" | "code"}
  -> register a session, return {state: "pending", qr_image_base64}

GET  /dashboard/whatsapp/link-status      (poll every 1.5–2s)
  -> pending | connecting | connected | expired | failed | idle

DELETE /dashboard/whatsapp
  -> best effort logout; always clear local state so re-link works
```

A real adapter stores the session credentials on disk (or in a vault), keyed by
`account_id`. Treat them as secrets: a session file is a full WhatsApp login.

## 4. Recommended implementations

| Option | Notes |
|---|---|
| **[whatsmeow](https://github.com/tulir/whatsmeow)** (Go) | what mautrix-whatsapp is built on; multi-device, QR + pairing code, groups, media, receipts |
| **[Baileys](https://github.com/WhiskeySockets/Baileys)** (TypeScript) | fastest to prototype; unofficial; protocol churn on WA updates |
| **mautrix-whatsapp + Matrix** | what Loop2 appears to run; gives you rooms, `mxc://` media, and a bridge status room for QR codes |
| **Meta Cloud API** | official, template-bound after 24h, per-message pricing |

Whatever you pick, put it behind `Channel` + `/internal/inbound` so the rest of
the system never learns which transport it is.

## 5. Production checklist

- [ ] per-number rate limits and jitter (bans are real; see §10 of the playbook)
- [ ] stop-on-refusal and quiet-hours enforced before the outbox
- [ ] reconnect/backoff for the session; surface `expired` and `failed`
- [ ] undelivered / decryption-failure alerts (the bridge should report them)
- [ ] media size + MIME validation, malware scan, short-lived signed URLs
- [ ] `x-internal-key` on every internal route, not exposed publicly
- [ ] delivery receipts → update `messages.status`
- [ ] an official Cloud API fallback for numbers you cannot risk

## 6. Legal

Linked-device automation is not sanctioned by WhatsApp/Meta. It can get a number
banned, and the ban is usually permanent. Ship it only with informed consent,
rate limits, and an official-API migration path.
