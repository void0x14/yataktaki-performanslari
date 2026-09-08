# ADR-001 — SQLite is retained; hot work and bulky payloads stay outside SQLite

Status: accepted (MASTER-PLAN §2)

SQLite is the control plane and durable result state. High-frequency per-IP UPDATE is forbidden.

- SQLite: ASN/prefix inventory, decision indexes, current state, validated endpoints, aggregates, audit metadata.
- Disk segment queue: large IP-port work lists, cursor, lease, checkpoint.
- Append-only payload store: raw Masscan, bulky L4 negatives, AI prompt/response payloads, archive events.
- Single DB Writer: the only process that writes SQLite, in batched idempotent transactions.
