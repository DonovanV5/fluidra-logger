# Maintenance Runbook

## Authoritative Data Source

- The logger's authoritative transactional store is the local SQLite database:
  - `data/fms_local_store.sqlite3`
- Google Sheets is a downstream sync target.
- Excel is a downstream export artifact rebuilt from SQLite.

## Normal Write Flow

1. Logger accepts an event only after local SQLite commit succeeds.
2. SQLite-backed events are exported to Excel.
3. SQLite-backed events are replayed to Google Sheets with idempotent sync.
4. `Scans` remains the canonical scan sheet.
5. `Sheet1` remains a compatibility sink until explicitly retired.

## If Google Sheets Is Down

- Expected behavior:
  - scanning can still continue if SQLite is healthy
  - local durability remains intact
  - Google write health degrades and backlog grows
- What to do:
  - keep the logger running if local SQLite is healthy
  - restore network, credentials, or workbook access
  - verify backlog drains after recovery
- Where to look:
  - logger health line: `S:` and `G:`
  - `logs/production.log`
  - `logs/production_errors.log`

## If Excel Export Fails

- Expected behavior:
  - scans/events can still be accepted if SQLite is healthy
  - Excel health degrades
- What to do:
  - verify the selected Excel path is reachable and writable
  - if the network share is unavailable, confirm local fallback path is in use
  - check file locks from Excel or another process
- Where to look:
  - logger health line: `E:`
  - `logs/production.log`

## If Local SQLite Fails

- Expected behavior:
  - scan acceptance should stop
  - production start/stop and downtime persistence should not continue silently
- What to do:
  - stop relying on the logger until local storage is healthy
  - check disk space, permissions, antivirus/file locks, and the `data` directory
  - confirm `data/fms_local_store.sqlite3` can be opened
- Where to look:
  - logger health line: `L:`
  - `logs/production.log`
  - `logs/production_errors.log`

## If Printer Fails

- Expected behavior:
  - printer health degrades
  - preview/label print attempts show warnings or errors
- What to do:
  - verify the Zebra printer is present in Windows
  - verify it is online and not in work-offline mode
  - check cable/network connection and printer power
  - confirm the configured printer name still matches Windows
- Where to look:
  - logger health line: `P:`
  - printer status field in the logger UI
  - `logs/production.log`

## If Teraoka Fails

- Expected behavior:
  - Teraoka health degrades
  - scanning and local durability should still continue unless another fault blocks them
- What to do:
  - verify whether Teraoka is enabled in user preferences
  - verify WSDL endpoint reachability
  - verify workcenter and supervisor settings
  - verify `config/Terioka_config.json` if that file is being used operationally
- Where to look:
  - logger health line: `T:`
  - Teraoka status fields in the logger UI
  - `logs/production.log`

## How To Inspect Sync Backlog

- Backlog lives in SQLite per sink.
- Quick summary from PowerShell:

```powershell
python -c "from local_event_store import LocalEventStore; s=LocalEventStore(r'C:\Developments\Fluidra_Manufacturing Solution\data\fms_local_store.sqlite3'); print(s.get_google_sync_summary())"
```

- Useful fields:
  - `pending_total`
  - `failed_total`
  - `scan_scans_pending`
  - `scan_sheet1_pending`
  - `production_pending`
  - `downtime_pending`

## How To Inspect Logs

- Logger logs:
  - `logs/production.log`
  - `logs/production_errors.log`
- Dashboard logs:
  - `logs/dashboard.log`
  - `logs/dashboard_errors.log`
- Startup self-checks are logged with explicit check names and states.

## How To Verify Dashboard Freshness

- Open the dashboard and check the health header.
- Confirm:
  - `Overall`
  - `Sheets`
  - `Reads`
  - `Refresh`
  - `Last OK`
  - `Last Fail`
- A healthy fresh dashboard should show a recent `Last OK`.
- If reads fail, cached data may remain visible while refresh health degrades.

## How To Back Up Local Data

- Stop the logger if possible before copying the database.
- Back up:
  - `data/fms_local_store.sqlite3`
  - `data/fms_local_store.sqlite3-wal` if present
  - `data/fms_local_store.sqlite3-shm` if present
  - `logs/`
  - `config/user_prefs.json` if present

## How To Recover Local Data

1. Stop the logger.
2. Restore the SQLite database and WAL/SHM sidecar files together if they exist.
3. Start the logger.
4. Confirm:
   - local store health is healthy
   - startup self-checks pass or show only expected warnings
   - pending Google backlog replays safely after connectivity returns
   - Excel export rebuilds from SQLite

## Startup Checklist

- `pumpline-logger.json` present
- `config/` directory present
- `data/` directory present
- SQLite writable
- workbook reachable
- `Products` and `Downtime` sheets reachable
- printer target present and ready
- Teraoka config state understood

## Known Transitional Areas

- `Sheet1` compatibility remains active.
- Excel bootstrap import remains as a migration bridge.
- Product data still comes from Google Sheets rather than SQLite.
- Dashboard ingest validation is strict but still preserves selected legacy compatibility where documented.
