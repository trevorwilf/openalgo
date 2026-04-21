# ADR 0001: Track A — market-family-agnostic core, one broker per instance

- **Status:** Accepted
- **Date:** 2026-04-21
- **Supersedes:** none
- **Superseded by:** none

## Context

OpenAlgo today is Indian-only by construction. Its instrument universe lives in
a single `symtoken` table (`database/symbol.py:33`) that every broker's master
contract downloader wipes and rewrites at login time via
`delete_symtoken_table()`. Only one broker's rows can coexist.

Credentials follow the same single-tenant shape: `BROKER_API_KEY` and
`BROKER_API_SECRET` are read from environment (`utils/config.py:18,28`) and
`blueprints/broker_credentials.py` edits the `.env` file in place to switch
brokers. A deployment holds at most one active broker session.

The user guide reinforces this positioning — the FAQ
(`docs/userguide/30-faqs/README.md:15`) describes OpenAlgo as "connects various
trading platforms to Indian stock brokers", and the supported-broker list is
Indian exclusively.

We have a refactor goal: make the *core* model market-family-agnostic so the
same codebase can one day host non-Indian equities and crypto without forking.
We need to decide how wide the "agnostic" goal goes.

## Decision

We adopt **Track A**: the internal domain model, persistence schema, and
service boundaries become market-family-agnostic, but the deployment model
stays **one broker per instance**. We do not take on multi-account,
multi-broker-session, or multi-user work in this refactor.

Concretely:

- The new normalized tables (`venues`, `instruments`, `broker_instrument_map`,
  `instrument_identifiers`, `instrument_sync_runs`) coexist across brokers.
  No `delete_symtoken_table`-style wipes in the new pipeline.
- The `auth` table and session model stay single-broker. A deployment still
  has one active broker at a time.
- Credential storage stays in `.env` through `blueprints/broker_credentials.py`.
  No per-user credential vault, no account switcher.
- `/api/v1` endpoints continue to assume a single broker context.

## Consequences

**Positive**

- The refactor is a *schema and vocabulary* change, not a tenancy change. It
  is finishable.
- Existing users' `.env`-based deployments keep working byte-for-byte.
- The SEBI static-IP mandate (see `CLAUDE.md` — "Security and Deployment
  Model") continues to apply cleanly: one IP, one broker, one deployment.

**Negative**

- Users wanting to trade multiple brokers from one instance still cannot.
- If a future ADR reverses this, the auth/session layer will need its own
  refactor — this one does not prepare for it.

**Neutral**

- Phase 2b's sync pipeline is additive and broker-tagged. If Track A is
  later widened to multi-broker, the sync tables already carry
  `broker_code` and do not need to be reshaped.

## References

- `CLAUDE.md` — "Security and Deployment Model" section
- `database/symbol.py:33` — legacy `SymToken` table definition
- `blueprints/broker_credentials.py:1-96` — `.env`-based credential model
- `utils/auth_utils.py:337` — `handle_auth_success` single-broker flow
- `docs/userguide/30-faqs/README.md:15` — Indian-broker framing
- `docs/adr/0002-no-specific-target-broker.md` — design target surface
- `docs/adr/0003-api-v1-frozen-v2-later.md` — API compatibility envelope
