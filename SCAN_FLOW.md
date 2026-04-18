# Scan Flow

## Old Flow
- Barcode entry was driven by `barcode_var.trace_add(...)`, which scheduled `_process_barcode_scan()` after a short delay.
- `handle_scan()` always read from the live entry field, performed duplicate detection, queued async logging, incremented production count, updated `last_scan_time`, updated the UI, and printed the label.
- The displayed cycle time was calculated after `last_scan_time` had already been overwritten, so the displayed delay was effectively `0.00 s` for the accepted scan.
- Duplicate popup "Mark as Reworked" called `handle_scan(..., increment_count=False)` and then separately called `log_scan_to_excel(..., status='Reworked')`, which risked:
  - re-entering the normal scan path
  - opening the duplicate flow again indirectly
  - double writes for one operator action
  - inconsistent scan acceptance vs persistence behavior
- The async scan logger had a fallback block that could attempt a second write and referenced locals that were not defined in that fallback scope.

## New Flow
- The trace-based trigger now keeps only one pending delayed scan callback at a time.
- `_process_barcode_scan()` logs a trace event and passes the stabilized barcode directly into `handle_scan(...)`.
- `handle_scan(...)` now supports explicit internal parameters for:
  - `barcode_override`
  - `status`
  - `notes`
  - `is_rework`
  - `allow_duplicate_prompt`
- A scan is processed through one path with a re-entry guard:
  - validate production/Teraoka readiness
  - reject empty input
  - run duplicate detection unless explicitly bypassed for approved rework
  - calculate cycle time from the previous `last_scan_time`
  - queue async persistence
  - only after the log request is queued, accept the scan into UI/count/print flow
- The async logger now performs one explicit persistence attempt per sink:
  - Excel
  - Google Sheets `Scans`
  - Google Sheets legacy `Sheet1`
- Health states now distinguish:
  - full success
  - partial durability
  - full persistence failure

## Scan Acceptance Rules
- A scan is **accepted** when all of the following are true:
  - production is running
  - Teraoka is ready when Teraoka mode is enabled
  - the barcode is non-empty
  - it is not routed to the duplicate popup
  - the async logging request is successfully queued
- A scan is **not accepted** when the background logging request cannot be queued.
- A scan is **durably logged** when at least one persistence sink succeeds:
  - Excel write succeeds, or
  - `Scans` append succeeds, or
  - `Sheet1` append succeeds
- Partial durability is represented by health states instead of silently looking like a full success.

## Duplicate And Rework Behavior
- Normal duplicate scans still open the existing duplicate popup.
- "Mark as Reworked" now uses the same main scan handler with:
  - `increment_count=False`
  - `status='Reworked'`
  - `is_rework=True`
  - `allow_duplicate_prompt=False`
- This preserves operator workflow but prevents:
  - duplicate popup re-entry
  - double writes
  - accidental double production increments
- Rework scans still follow the accepted-scan workflow for UI/print timing, but they do not increment production count.

## Health And Persistence Meaning
- `scan_write`
  - `OK`: Excel, `Scans`, and `Sheet1` all succeeded
  - `WARNING`: scan accepted and at least one sink succeeded, but one or more sinks failed
  - `ERROR`: log request failed or all persistence sinks failed
  - `UNKNOWN`: no completed scan-write outcome yet
- `excel`
  - continues to represent the Excel sink specifically
- `google_write`
  - continues to represent Google Sheets append health specifically

## Known Remaining Limitations
- The logger still uses a background thread for scan persistence; this phase makes the outcomes explicit but does not redesign the threading model.
- UI updates and health updates are still triggered from the existing runtime model; this phase does not introduce a broader thread-marshalling refactor.
- Duplicate detection still intentionally allows a scan through if Google Sheets lookup fails and no cached duplicate is available; that business policy was preserved.
- Legacy dual-write behavior to both `Scans` and `Sheet1` remains in place.
