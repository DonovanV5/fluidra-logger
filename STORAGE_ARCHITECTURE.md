# Storage Architecture

## Phase Scope
This phase moves the logger to a local SQLite-first storage model without removing:

- Google Sheets integration
- legacy dual-write compatibility to `Scans` and `Sheet1`
- Excel export capability

The dashboard was not changed in this phase.

## Old Write Path

### Scans
1. `handle_scan(...)` accepted the scan once the async Excel/Google worker was queued.
2. `_async_log_scan(...)` rewrote `barcode_log.xlsx`.
3. `_async_log_scan(...)` appended the same scan row to Google Sheets `Scans`.
4. `_async_log_scan(...)` appended the same scan row to Google Sheets `Sheet1`.
5. In-memory duplicate caches were only updated after downstream sink success.

### Production Events
1. `start_production(...)` and `stop_production(...)` changed runtime state.
2. The methods appended directly to Google Sheets `Production`.
3. No local durable event store existed for production session events.

### Downtime Events
1. `resume_production(...)` and `end_downtime(...)` built downtime rows.
2. The methods appended directly to Google Sheets `Downtime`.
3. No local durable downtime event store existed.

### Startup Sync
1. The logger loaded duplicate history mainly from Excel and Google Sheets.
2. `sync_all_to_google_sheets()` used Excel as the startup source for scan sync.

## New Write Path

### Authoritative Local Commit
The primary transactional store is now the local SQLite database at:

- [fms_local_store.sqlite3](C:/Developments/Fluidra_Manufacturing%20Solution/data/fms_local_store.sqlite3)

The logger now separates persistence into three stages:

1. Local durable write
2. Google Sheets outbound sync
3. Excel export/update

### Scans
1. `log_scan_to_excel(...)` builds the canonical scan row.
2. The scan is inserted into SQLite first.
3. A scan is only accepted after that SQLite commit succeeds.
4. Once committed locally, the scan barcode is added to the in-memory duplicate sets immediately.
5. A background worker exports the full local store to Excel.
6. The same background worker appends the scan to:
   - `Scans`
   - `Sheet1`
7. Google/Excel sink state is tracked separately from the local durable commit.

### Production Events
1. `start_production(...)` builds a canonical `PRODUCTION_START` row.
2. The event is inserted into SQLite first.
3. If the local commit fails, production is not started.
4. After local commit, a background worker:
   - refreshes Excel export
   - syncs pending `Production` rows to Google Sheets

The same pattern applies to `stop_production(...)` with `PRODUCTION_END`.

### Downtime Events
1. `resume_production(...)` and `end_downtime(...)` build canonical downtime rows.
2. The downtime event is inserted into SQLite first.
3. If the local commit fails, the downtime dialog remains active and the action is not completed.
4. After local commit, a background worker:
   - refreshes Excel export
   - syncs pending `Downtime` rows to Google Sheets

### Startup Behavior
1. The logger initializes SQLite first.
2. If the local scan table is empty and `barcode_log.xlsx` already exists, existing scan rows are imported once into SQLite as a bootstrap step.
3. Bootstrap-imported Excel scan rows are marked as already synced/exported to avoid duplicate replay to Google Sheets.
4. Duplicate caches are then loaded from SQLite and augmented with Google Sheets history for compatibility.
5. Startup sync now replays pending local SQLite events to:
   - Excel export
   - Google Sheets `Scans`
   - Google Sheets `Sheet1`
   - Google Sheets `Production`
   - Google Sheets `Downtime`

## Local Tables

The SQLite store is implemented in [local_event_store.py](C:/Developments/Fluidra_Manufacturing%20Solution/local_event_store.py).

### `scan_events`
- canonical scan row payload
- normalized barcode for duplicate lookup
- local commit timestamp
- Excel export state
- Google `Scans` sync state
- Google `Sheet1` sync state
- per-sink attempt counters and last-error fields

### `production_events`
- canonical production row payload
- event type
- local commit timestamp
- Excel export state
- Google `Production` sync state
- sync attempt counter and last error

### `downtime_events`
- canonical downtime row payload
- reason/workcenter index fields
- local commit timestamp
- Excel export state
- Google `Downtime` sync state
- sync attempt counter and last error

## What Is Authoritative Now

After this phase, the authoritative live transaction source is SQLite, not Excel.

### Authoritative
- local SQLite rows for scans
- local SQLite rows for production events
- local SQLite rows for downtime events

### Downstream / Derived
- Google Sheets rows
- Excel workbook export
- in-memory duplicate caches

## Excel After This Phase

Excel is now an export/report artifact:

- the workbook is rebuilt from SQLite
- it no longer decides whether a scan is accepted
- it no longer seeds the live scan path except for one-time bootstrap migration into SQLite when the DB is empty

The workbook currently exports:

- `Scans`
- `Production`
- `Downtime`

The file path remains:

- [barcode_log.xlsx](C:/Developments/Fluidra_Manufacturing%20Solution/barcode_log.xlsx)

or the configured network-path variant when available.

## Google Sheets After This Phase

Google Sheets remains an outbound compatibility sink:

- scans still sync to `Scans`
- scans still sync to `Sheet1`
- production events still sync to `Production`
- downtime events still sync to `Downtime`

Google Sheets failures now leave the local SQLite row intact for later retry.

## Compatibility Behavior Still Present

- `Sheet1` scan sync remains in place
- duplicate barcode fallback still checks Google Sheets as a final compatibility lookup
- the legacy `sync_to_google_sheets(df)` scan-only full-sheet helper remains in code as a compatibility wrapper, but it is no longer the primary startup path
- Excel path fallback behavior remains in place

## Migration Notes

### Old Excel-centric assumptions removed
- Scan acceptance no longer depends on Excel or Google Sheets worker queueing.
- Duplicate history is no longer loaded primarily from Excel.
- Startup replay no longer uses Excel as the primary source of truth.

### Transitional behavior that remains until Phase 8
- Google sync is still append-based and not yet fully idempotent across all historical scenarios.
- `Sheet1` coexistence is still preserved.
- Duplicate fallback still uses Google Sheets as a remote compatibility source.
- Bootstrap import only migrates scan history from Excel; historical production/downtime data is not backfilled from Google Sheets in this phase.
