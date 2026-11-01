# Architecture

## Module map

```
apps/api/app
├── main.py             FastAPI app, lifespan (seed, outbox worker, ticker)
├── config.py           env-driven settings
├── db.py               SQLite connection + schema bootstrap
├── schema.sql          tables and indexes
├── repo.py             all SQL; JSON columns decoded here
├── schemas.py          pydantic request bodies
├── security.py         OTP + opaque session tokens
├── deps.py             session → partner → account scope
├── seed.py             idempotent demo tenant
├── migrations.py       in-place upgrade: orgs for existing partners
├── routers/
│   ├── auth.py         request/verify OTP, session, logout
│   ├── accounts.py     accounts, quota, pause setting, insights
│   ├── rooms.py        chats, transcripts, exclusions, owner reply
│   ├── agents.py       agents, lanes, memory, follow-ups, knowledge attach
│   ├── chat.py         dashboard thread (same pipeline as WhatsApp)
│   ├── scheduling.py   jobs (RRULE) + one-shot tasks
│   ├── webhooks.py     agent tools with deliveries
│   ├── knowledge.py    sources + entries
│   ├── channels.py     WhatsApp link lifecycle
│   ├── models.py       live model catalogue (OpenRouter)
│   ├── workspace.py    overview, connections
│   ├── organizations.py  orgs, members, roles, invitations
│   ├── billing.py      plans, subscriptions, usage, provider webhooks
│   └── internal.py     bridge ingress, notifications, Meta webhook, health
├── services/
│   ├── inbound.py      gate → match → assemble → run → admit
│   ├── outbound.py     outbox queue + worker (transport truth)
│   ├── scheduler.py    follow-ups, jobs, tasks (time truth)
│   ├── knowledge.py    keyword retrieval
│   ├── notifications.py  OTP / link / account alerts into the assistant inbox
│   ├── models.py       OpenRouter catalogue: fetch, normalise, cache, degrade
│   └── rrule.py        minimal iCalendar recurrence
├── agent/
│   ├── runtime.py      the bounded tool loop
│   ├── tools.py        tool specs + the only place side effects happen
│   ├── capabilities.py permissions
│   └── prompts.py      system prompt + transcript assembly
├── llm/                provider contract, echo, OpenAI-compatible
└── channels/           channel contract, stub, Meta Cloud API
```

## One inbound message

```
adapter ──POST /internal/inbound──► ensure_room
                                      │
                       ┌──────────────┴───────────────┐
                       │ 1. history (before insert)   │
                       │ 2. insert message            │  ← persisted before anything else
                       │ 3. gates: excluded / pause / │
                       │    subscription / no agent   │
                       │ 4. match agent (scope, chat  │
                       │    type, exclusions, topic)  │
                       │ 5. run_agent                 │
                       │    system prompt + memory +  │
                       │    knowledge + tools loop    │
                       │ 6. admit: insert outbound    │
                       │    (status=accepted) + outbox│
                       └──────────────┬───────────────┘
                                      │ 202 { accepted, stage, run_id }
                          outbox worker (async)
                                      │ channel.send()
                                      ▼
                       message.status → delivered | failed
```

A dashboard message takes the same path with `source="dashboard"`.

The partner's own thread (`rooms.kind='system'`, external id `system`) is the
assistant inbox. System events are inserted directly by
`services/notifications.py` so they never enter the agent pipeline or produce a
reply; `/dashboard/chat/messages` defaults to it, which is what the Assistant
screen shows first.

## Tenancy

Three tables carry it: `organizations`, `memberships(org_id, pid, role)`,
`accounts.org_id`. Everything else is account-scoped, so isolating a new feature
means scoping it by `account_id` (and therefore org) in `repo.py`.

`deps.current_org` checks membership on every dashboard request; `current_account`
checks the account belongs to that org. Roles are enforced by `require_writer`
(mutations) and `admin_only` / `manager_up` (billing, team, configuration).
Plan limits are enforced by `services/billing.check()` at the send boundary and
when adding numbers — never in the UI.

## State that matters

| State | Owner | Meaning |
|---|---|---|
| `messages.status` | thread | `accepted → delivered｜failed` |
| `outbox.status` | transport | `queued → sent｜failed` |
| `runs.status` | runtime | `ok｜read_only｜handover｜limit｜error` |
| `lanes.handed_over` | human-in-the-loop | no automated replies until cleared |
| `followup_runs` | scheduler | one row per fired rule, prevents double sends |
| `settings.human_active_pause` | account | pause after the owner speaks |

Three separate statuses is deliberate: a message can be persisted, admitted and
still fail to deliver; collapsing them loses the only signal support needs.

## Runtime contract

```python
outcome = await run_agent(agent, account, room, text=..., history=...)
# RunOutcome(status, reply, iterations, tokens, stage, reason, handed_over)
```

* bounded by `max_iterations` and `timeout_seconds`
* tools execute with capability checks; a denied tool returns an error to the
  model, it does not raise
* handover is a tool (`request_handover`), recorded on the lane
* the runtime never sends: admission is the caller's job

## Web shell

`apps/web/app/dashboard/layout.tsx` owns the shell (sidebar, banner, quota,
profile) behind a `WorkspaceProvider` that resolves session → accounts once.
Pages are client components that read the API through `lib/api.ts`; there is no
server state on the frontend, which is what makes the static Cloudflare build
work. Adding a page means adding a route folder and one entry in the `NAV`
array.

## Extension points

| Want | Touch |
|---|---|
| New tool | `agent/tools.py`: spec + execute branch |
| New model provider | `llm/`: implement `complete`, register in `get_llm` |
| New transport | `channels/`: implement `Channel` |
| Mongo/Postgres | `repo.py` (all SQL is here) |
| Per-account transport | add `accounts.channel`, branch in `outbound.deliver` |
| Embedding retrieval | `services/knowledge.py:search` |
| Cron beyond RRULE | replace `services/rrule.py` with `dateutil.rrule` |

## Known limitations

* SQLite + a global lock: fine for one process, not for horizontal scale.
* In-process worker/ticker: a restart can lose a queued tick (rows survive, but
  no leader election — run exactly one API instance, or move to a real queue).
* Topic matching is keyword-based; the product's matcher is likely LLM-assisted.
* No media upload pipeline, no vision extraction, no billing, no org roles.
* Test runs write to real memory/handover flags (noted in the endpoint docstring).
