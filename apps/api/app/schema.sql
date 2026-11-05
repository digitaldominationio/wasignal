PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS organizations (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  name             TEXT NOT NULL,
  slug             TEXT UNIQUE,
  owner_pid        INTEGER NOT NULL REFERENCES partners(pid),
  default_provider TEXT,
  default_model    TEXT,
  created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_credentials (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id            INTEGER NOT NULL REFERENCES organizations(id),
  provider          TEXT NOT NULL,
  encrypted_key     TEXT NOT NULL,
  nonce             TEXT NOT NULL,
  key_hint          TEXT NOT NULL DEFAULT '',
  base_url          TEXT,
  status            TEXT NOT NULL DEFAULT 'active',   -- active | invalid | revoked
  created_by        INTEGER,
  created_at        INTEGER NOT NULL,
  updated_at        INTEGER NOT NULL,
  last_validated_at INTEGER,
  last_used_at      INTEGER,
  UNIQUE (org_id, provider)
);

CREATE TABLE IF NOT EXISTS memberships (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id     INTEGER NOT NULL REFERENCES organizations(id),
  pid        INTEGER NOT NULL REFERENCES partners(pid),
  role       TEXT NOT NULL DEFAULT 'member',   -- owner | admin | manager | member | viewer
  created_at INTEGER NOT NULL,
  UNIQUE (org_id, pid)
);
CREATE INDEX IF NOT EXISTS idx_memberships_pid ON memberships(pid);

CREATE TABLE IF NOT EXISTS invitations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id      INTEGER NOT NULL REFERENCES organizations(id),
  phone       TEXT NOT NULL,
  role        TEXT NOT NULL DEFAULT 'member',
  token       TEXT NOT NULL UNIQUE,
  invited_by  INTEGER NOT NULL,
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  accepted_at INTEGER,
  declined_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_invitations_org ON invitations(org_id, accepted_at);

CREATE TABLE IF NOT EXISTS plans (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  price_inr     INTEGER NOT NULL,
  period        TEXT NOT NULL,
  tagline       TEXT NOT NULL DEFAULT '',
  features_json TEXT NOT NULL DEFAULT '[]',
  limits_json   TEXT NOT NULL DEFAULT '{}',
  lookup_key    TEXT NOT NULL,
  recommended   INTEGER NOT NULL DEFAULT 0,
  sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id              INTEGER NOT NULL UNIQUE REFERENCES organizations(id),
  plan_id             TEXT NOT NULL REFERENCES plans(id),
  status              TEXT NOT NULL DEFAULT 'trialing',  -- trialing | active | past_due | canceled
  current_period_start INTEGER NOT NULL,
  current_period_end   INTEGER NOT NULL,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
  provider            TEXT NOT NULL DEFAULT 'manual',    -- stripe | dodo | manual
  provider_ref        TEXT,
  created_at          INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id   INTEGER NOT NULL REFERENCES organizations(id),
  metric   TEXT NOT NULL,        -- messages | runs | numbers
  quantity INTEGER NOT NULL DEFAULT 1,
  ts       INTEGER NOT NULL,
  ref      TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_org_metric_ts ON usage_events(org_id, metric, ts);

CREATE TABLE IF NOT EXISTS partners (
  pid           INTEGER PRIMARY KEY AUTOINCREMENT,
  phone         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL DEFAULT '',
  wa_linked     INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  partner_pid         INTEGER NOT NULL REFERENCES partners(pid),
  org_id              INTEGER REFERENCES organizations(id),
  name                TEXT NOT NULL,
  wa_number           TEXT NOT NULL DEFAULT '',
  timezone            TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  subscription_status TEXT NOT NULL DEFAULT 'active',
  created_at          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token       TEXT PRIMARY KEY,
  partner_pid INTEGER NOT NULL REFERENCES partners(pid),
  expires_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS otps (
  phone      TEXT PRIMARY KEY,
  code       TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rooms (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id       INTEGER NOT NULL REFERENCES accounts(id),
  external_id      TEXT NOT NULL,
  kind             TEXT NOT NULL DEFAULT 'dm',        -- dm | group
  display_name     TEXT NOT NULL DEFAULT '',
  is_excluded      INTEGER NOT NULL DEFAULT 0,
  last_activity_at INTEGER NOT NULL DEFAULT 0,
  UNIQUE (account_id, external_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  INTEGER NOT NULL REFERENCES accounts(id),
  room_id     INTEGER NOT NULL REFERENCES rooms(id),
  direction   TEXT NOT NULL,                          -- in | out
  sender      TEXT NOT NULL DEFAULT '',
  sender_name TEXT NOT NULL DEFAULT '',
  text        TEXT NOT NULL DEFAULT '',
  media_json  TEXT NOT NULL DEFAULT '[]',
  ts          INTEGER NOT NULL,
  status      TEXT NOT NULL DEFAULT 'delivered',      -- accepted | persisted | delivered | failed
  source      TEXT NOT NULL DEFAULT 'whatsapp',       -- whatsapp | dashboard | job | task | notify
  agent_id    INTEGER,
  run_id      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_account_ts ON messages(account_id, ts);

CREATE TABLE IF NOT EXISTS agents (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id          INTEGER NOT NULL REFERENCES accounts(id),
  name                TEXT NOT NULL,
  system_prompt       TEXT NOT NULL,
  trigger_type        TEXT NOT NULL DEFAULT 'event',   -- scheduled | event | hybrid
  trigger_scope       TEXT NOT NULL DEFAULT 'room',    -- room | topic
  trigger_condition   TEXT,
  room_id             INTEGER,
  chat_type           TEXT NOT NULL DEFAULT 'all',     -- all | dm | group
  excluded_rooms_json TEXT NOT NULL DEFAULT '[]',
  capabilities_json   TEXT NOT NULL DEFAULT '["read","send"]',
  tool_suites_json    TEXT NOT NULL DEFAULT '[]',
  webhook_ids_json    TEXT NOT NULL DEFAULT '[]',
  llm_provider        TEXT,
  llm_model           TEXT,
  recurrence_cron     TEXT,
  timezone            TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  max_iterations      INTEGER NOT NULL DEFAULT 6,
  timeout_seconds     INTEGER NOT NULL DEFAULT 60,
  max_memory_chars    INTEGER NOT NULL DEFAULT 4000,
  status              TEXT NOT NULL DEFAULT 'active',  -- active | paused
  created_at          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lanes (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id       INTEGER NOT NULL REFERENCES agents(id),
  room_id        INTEGER NOT NULL REFERENCES rooms(id),
  lane_key       TEXT NOT NULL DEFAULT 'main',
  session_memory TEXT NOT NULL DEFAULT '',
  pending_steps  TEXT NOT NULL DEFAULT '[]',
  handed_over    INTEGER NOT NULL DEFAULT 0,
  last_run_at    INTEGER NOT NULL DEFAULT 0,
  UNIQUE (agent_id, room_id, lane_key)
);

CREATE TABLE IF NOT EXISTS memory (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  key      TEXT NOT NULL,
  value    TEXT NOT NULL,
  UNIQUE (agent_id, key)
);

CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id    INTEGER NOT NULL REFERENCES agents(id),
  account_id  INTEGER NOT NULL,
  room_id     INTEGER,
  lane        TEXT NOT NULL DEFAULT 'main',
  trigger     TEXT NOT NULL DEFAULT 'event',           -- event | schedule | test
  status      TEXT NOT NULL DEFAULT 'running',         -- running | ok | read_only | handover | error | limit
  stage       TEXT NOT NULL DEFAULT 'assembling',
  reason      TEXT,
  iterations  INTEGER NOT NULL DEFAULT 0,
  tokens      INTEGER NOT NULL DEFAULT 0,
  reply       TEXT NOT NULL DEFAULT '',
  llm_provider TEXT,
  llm_model    TEXT,
  tool_calls_json TEXT NOT NULL DEFAULT '[]',
  started_at  INTEGER NOT NULL,
  finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_agent_started ON runs(agent_id, started_at);

CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id    INTEGER NOT NULL,
  context_json  TEXT NOT NULL,
  rrule         TEXT NOT NULL,
  dtstart_local TEXT NOT NULL,
  until_local   TEXT,
  next_run_at   INTEGER,
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_fired_at INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id         INTEGER NOT NULL,
  context_json       TEXT NOT NULL,
  execute_after_at   INTEGER NOT NULL,
  status             TEXT NOT NULL DEFAULT 'pending'    -- pending | done | paused
);

CREATE TABLE IF NOT EXISTS knowledge_sources (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id             INTEGER NOT NULL,
  name                   TEXT NOT NULL,
  source_room_id         TEXT NOT NULL,
  source_type            TEXT NOT NULL DEFAULT 'whatsapp_room',
  extraction_instruction TEXT NOT NULL DEFAULT '',
  status                 TEXT NOT NULL DEFAULT 'ready',
  created_at             INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_entries (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id   INTEGER NOT NULL REFERENCES knowledge_sources(id),
  keys_json   TEXT NOT NULL DEFAULT '[]',
  title       TEXT NOT NULL DEFAULT '',
  content     TEXT NOT NULL DEFAULT '',
  medias_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_knowledge (
  agent_id   INTEGER NOT NULL REFERENCES agents(id),
  source_id  INTEGER NOT NULL REFERENCES knowledge_sources(id),
  PRIMARY KEY (agent_id, source_id)
);

CREATE TABLE IF NOT EXISTS webhooks (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id      INTEGER NOT NULL,
  name            TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  url             TEXT NOT NULL,
  method          TEXT NOT NULL DEFAULT 'POST',
  headers_json    TEXT NOT NULL DEFAULT '[]',
  body_fields_json TEXT NOT NULL DEFAULT '[]',
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  webhook_id  INTEGER NOT NULL,
  account_id  INTEGER NOT NULL,
  trigger     TEXT NOT NULL DEFAULT 'agent',           -- agent | test
  status_code INTEGER,
  duration_ms INTEGER,
  error       TEXT,
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS followup_rules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  INTEGER NOT NULL,
  scope       TEXT NOT NULL DEFAULT 'agent',           -- agent | label
  ref_id      INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1,
  rules_json  TEXT NOT NULL DEFAULT '[]',
  window_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS followup_runs (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id   INTEGER NOT NULL,
  room_id   INTEGER NOT NULL,
  rule_key  TEXT NOT NULL,
  due_at    INTEGER NOT NULL,
  sent_at   INTEGER,
  status    TEXT NOT NULL DEFAULT 'pending'            -- pending | sent | skipped
);

CREATE TABLE IF NOT EXISTS settings (
  account_id         INTEGER PRIMARY KEY,
  human_active_pause INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS outbox (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  room_id    INTEGER NOT NULL,
  message_id INTEGER,
  text       TEXT NOT NULL,
  media_json TEXT NOT NULL DEFAULT '[]',
  status     TEXT NOT NULL DEFAULT 'queued',           -- queued | sent | failed
  error      TEXT,
  created_at INTEGER NOT NULL,
  sent_at    INTEGER
);


CREATE TABLE IF NOT EXISTS connected_accounts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id        INTEGER NOT NULL REFERENCES organizations(id),
  service       TEXT NOT NULL,                 -- google_calendar | gmail
  toolkit       TEXT NOT NULL,                 -- broker toolkit slug
  provider      TEXT NOT NULL DEFAULT 'composio',
  external_id   TEXT,
  status        TEXT NOT NULL DEFAULT 'pending', -- pending | active | expired | failed | revoked
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  UNIQUE (org_id, service)
);

CREATE TABLE IF NOT EXISTS integration_actions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id      INTEGER NOT NULL,
  account_id  INTEGER,
  agent_id    INTEGER,
  room_id     INTEGER,
  service     TEXT NOT NULL,
  action      TEXT NOT NULL,
  args_json   TEXT NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'ok',      -- ok | error | proposed
  result_json TEXT NOT NULL DEFAULT '{}',
  error       TEXT,
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_org ON integration_actions(org_id, id);

CREATE TABLE IF NOT EXISTS pending_actions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id     INTEGER NOT NULL,
  agent_id   INTEGER NOT NULL,
  room_id    INTEGER NOT NULL,
  lane_key   TEXT NOT NULL DEFAULT 'main',
  service    TEXT NOT NULL,
  action     TEXT NOT NULL,
  args_json  TEXT NOT NULL DEFAULT '{}',
  token      TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending',  -- pending | executed | cancelled | expired
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_lane ON pending_actions(agent_id, room_id, lane_key, status);


CREATE TABLE IF NOT EXISTS broker_credentials (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id           INTEGER NOT NULL UNIQUE REFERENCES organizations(id),
  provider         TEXT NOT NULL DEFAULT 'composio',
  encrypted_key    TEXT NOT NULL,
  nonce            TEXT NOT NULL,
  key_hint         TEXT NOT NULL DEFAULT '',
  base_url         TEXT,
  auth_configs_json TEXT NOT NULL DEFAULT '{}',
  status           TEXT NOT NULL DEFAULT 'active',
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL
);
