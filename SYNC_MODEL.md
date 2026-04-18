# Sync Model

## Goal

Phase 8 keeps SQLite as the authoritative local event store and makes outbound Google Sheets sync retry-safe and idempotent.

## Old Model

- Logger committed events locally in SQLite first.
- Google sync replay read pending rows from SQLite.
- Downstream writes to `Scans`, `Sheet1`, `Production`, and `Downtime` still used append-only behavior.
- If Google append succeeded but the local sync flag update failed or the app stopped at the wrong moment, the next retry could append the same event again.

## New Model

- Every locally committed event already has a stable `event_id` in SQLite.
- Google sync now uses that `event_id` as the outbound identity key.
- Before any append, the logger:
  - ensures the worksheet has a `Sync Event ID` column
  - looks for an existing row with the same `Sync Event ID`
  - if not found, attempts legacy reconciliation by matching the row payload exactly
  - backfills `Sync Event ID` on a matched legacy row
  - appends only if no existing or reconciled row is found

## Authoritative Source

- SQLite is still authoritative for logger durability.
- Google Sheets is a downstream compatibility/reporting sink.
- Excel remains a downstream export artifact.

## Event Identifiers

- Local event identity: `event_id`
- Event ID source: SQLite row primary key generated at local commit time
- Downstream transport field: `Sync Event ID`
- `Sync Event ID` is transport metadata for synchronization and is not part of the canonical business schema in `SCHEMA_CONTRACT.md`.

## Per-Sink Sync State

SQLite now tracks per-sink state for outbound Google sync:

- `pending`
  - local event exists and that sink has not been confirmed yet
- `synced`
  - sink row is confirmed by append or reconciliation
- `failed`
  - last sink attempt failed and the event remains pending for retry

Tracked fields now include, per sink where applicable:

- synced flag
- synced timestamp
- state
- retry/attempt count
- last error
- last attempted timestamp
- downstream row reference if available

### Scan Event Sinks

Each scan event tracks Google sync separately for:

- `Scans`
- `Sheet1`

This preserves dual-write compatibility while allowing one sink to succeed and the other to remain pending.

### Production and Downtime Sinks

Production and downtime events each track one Google sink:

- `Production`
- `Downtime`

## Retry Behavior

- Retry source of truth is always SQLite pending state.
- A retry does not append blindly.
- A retry first searches by `Sync Event ID`.
- If the row predates the metadata column, retry falls back to exact payload reconciliation.
- On success, the local sink state becomes `synced`.
- On failure, the local sink state becomes `failed`, the attempt counter increments, and the error is stored.

## Duplicate Prevention Strategy

Duplicate downstream rows are prevented by this order:

1. Local event is identified by stable SQLite `event_id`.
2. Google sheet is searched for that `event_id` in `Sync Event ID`.
3. If not found, existing rows are compared against the event payload.
4. If a payload match is found, the existing row is adopted and annotated with `Sync Event ID`.
5. Only unmatched events are appended.

## Startup Replay After Phase 8

- Startup replay still exports SQLite state to Excel.
- Startup replay still retries pending Google events for:
  - `Scans`
  - `Sheet1`
  - `Production`
  - `Downtime`
- Restarting during a pending or partially completed sync no longer relies on append-only behavior.
- On restart, pending events are reconciled first and only appended if not already present downstream.

## Observability

- Logger health still reflects Google connectivity and write degradation.
- SQLite now stores explicit retry/backlog details per sink for later inspection.
- Logger logs now distinguish:
  - already-present downstream rows
  - reconciled legacy rows
  - real append failures
  - remaining pending/failed backlog

## Transitional Behavior Still Kept

- `Sheet1` dual-write compatibility remains active.
- Google Sheets remains a downstream sink and is not yet a fully separate sync service.
- `Products` remains outside SQLite in this phase.
- Historical rows created before `Sync Event ID` may still require payload reconciliation until legacy rows are fully annotated.
