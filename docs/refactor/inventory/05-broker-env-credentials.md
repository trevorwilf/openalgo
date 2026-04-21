# Inventory 05 — Broker credential reads from `.env`

## Summary

Broker credentials are a single-tenant `.env`-sourced pair:
`BROKER_API_KEY` and `BROKER_API_SECRET`. `utils/config.py:18,28`
exposes accessors. `blueprints/brlogin.py` reads them via `os.getenv`
directly at module scope (line 24) and in per-broker callback handlers.
`blueprints/broker_credentials.py` edits the `.env` file in place to
switch brokers. No credential vault, no per-user secret storage, no
HashiCorp-Vault-style indirection.

ADR 0001 (Track A) locks this model: single broker per instance, one
credential pair per deployment. This inventory documents every
`.env`-touching site so future refactors can see the whole surface
before proposing a change.

## Raw citations

```
# Accessor definitions
utils/config.py:18     def get_broker_api_key() -> str | None  (os.getenv("BROKER_API_KEY"))
utils/config.py:28     def get_broker_api_secret() -> str | None

# Module-scope reads (executed at import time)
blueprints/brlogin.py:13-18,24  from utils.config import get_broker_api_key,...
blueprints/brlogin.py:24        BROKER_API_KEY = get_broker_api_key()

# Per-broker handler-scope reads (inside request handlers)
blueprints/brlogin.py:154,316,518,538,811,881,882   os.getenv("BROKER_API_KEY")
blueprints/auth.py:76                                BROKER_API_KEY = os.getenv("BROKER_API_KEY")
blueprints/auth.py:81                                serialized into response payload

# Credentials management endpoint (reads and writes .env)
blueprints/broker_credentials.py:20    def get_env_path()  (resolves to project-root/.env)
blueprints/broker_credentials.py:26    def read_env_file()
blueprints/broker_credentials.py:41    def update_env_value()
blueprints/broker_credentials.py:105-108,255-270  GET returns masked creds; POST writes .env
blueprints/broker_credentials.py:336-363  GET /api/broker/capabilities (uses session broker, not env)

# Broker modules that read their own SDK keys from env (non-exhaustive)
broker/*/api/auth_api.py               many use os.getenv for OAuth client_id etc.
```

## Blast radius

- **Phase 1b (plugin capabilities)** — `GET /api/broker/capabilities`
  keeps returning the same shape for existing keys (`broker_type`,
  `supported_exchanges`, `leverage_config`) and adds richer fields;
  no credential changes.
- **Phase 4 (venue/session normalization)** — no changes to credential
  storage.
- **Phase 5 (frontend)** — the credentials page
  (`/apikey`, `blueprints/broker_credentials.py:99-333`) keeps its v1
  shape. Frontend consumers unaffected.
- Track A does **NOT** introduce per-user or per-broker credential
  vaulting. See `docs/adr/0001-track-a-scope.md`.

Invariant: single-broker per deployment. Changes to this model are
out of scope.
