# SAFE BASELINE

## Purpose

This document records the current live-system shape before functional refactors.
The goal of this phase was to understand the logger/dashboard runtime paths and add
lightweight observability without changing business behavior.

## System Map

### Logger application

- File: `Fluidra_Manufacturing_Solutionv7.4.py`
- Main entry:
  - module-level Google Sheets authentication
  - `BarcodeApp`
  - `if __name__ == '__main__':` application bootstrap
- Main classes/functions:
  - `StartupScreen`
  - `BarcodeApp`
  - `get_product_info(product_code)`
  - `initialize_excel_log()`
  - `sync_all_to_google_sheets()`
  - `sync_to_google_sheets(df)`
  - `log_scan_to_excel()`
  - `_async_log_scan()`
  - `is_duplicate_barcode()`
  - `_barcode_exists_in_sheets()`
  - `handle_duplicate_barcode()`
  - `check_auto_downtime()`
  - `start_production()`
  - `stop_production()`
  - `check_production_schedule()`
  - `resume_production()`
  - `end_downtime()`
  - `update_printer_status()`
  - `print_label()`

### Dashboard application

- File: `plant_dashboard.py`
- Main entry:
  - module-level `DataStore()` creation and initial refresh
  - Dash callback graph/table update pipeline
  - `if __name__ == '__main__':` Dash server start
- Main classes/functions:
  - `DataStore`
  - `DataStore._init_gsheets()`
  - `DataStore._read_sheet()`
  - `DataStore.refresh()`
  - `DataStore._clean_scans()`
  - `DataStore._clean_production()`
  - `DataStore._clean_downtime()`
  - `DataStore._backfill_downtime_workcenters()`
  - `_normalize_downtime_events()`
  - `_build_production_sessions()`
  - `_compute_clipped_downtime_metrics()`
  - `update_all()`
  - `_update_all_impl()`

### Config and integration files

- File: `pumpline-logger.json`
  - Google service-account credentials used by both logger and dashboard.
- File: `config/user_prefs.json`
  - Logger runtime preferences:
  - last workcenter, selected ZPL preset, Teraoka enablement, auto-production times, custom ZPL directory.
- File: `config/terioka_config.json`
  - Workcenter list plus Teraoka WSDL and default supervisor.
- File: `config/production_schedule.json`
  - Dashboard production schedule and break windows used in OEE/scheduled-break calculations.
- File: `teraoka_client.py`
  - Teraoka/WMS background client used by the logger.
- File: `barcode_log.xlsx`
  - Logger Excel sink and startup sync source.

## Current Data Flows

### 1. Production scan flow

- Operator scans barcode into `BarcodeApp`.
- Logger blocks scanning when production is not running.
- Logger optionally blocks scanning when Teraoka is enabled but not connected/jobless.
- Duplicate check order:
  - in-memory `scanned_barcodes`
  - in-memory Google Sheets cache
  - direct Google Sheets lookup in `Scans`, then legacy `Sheet1`
- On accepted scan:
  - product metadata is read from Google Sheets `Products`
  - scan row is written to local/network `barcode_log.xlsx`
  - scan row is appended to Google Sheets `Scans`
  - same scan row is also appended to legacy Google Sheets `Sheet1`
  - label is printed to Zebra printer
  - Teraoka receipt is enqueued when enabled

### 2. Production start/stop flow

- Logger starts production manually or from schedule logic in `check_production_schedule()`.
- Start appends a `PRODUCTION_START` row into Google Sheets `Production`.
- Stop appends a `PRODUCTION_END` row into Google Sheets `Production`.
- Dashboard reads `Production` and reconstructs production sessions from those events.

### 3. Downtime flow

- Downtime can be auto-detected when elapsed time since last scan exceeds `2.5 * expected_cycle`.
- Operator resumes production through the downtime popup.
- Logger writes downtime rows to Google Sheets `Downtime` with:
  - `Timestamp`
  - `Duration (sec)`
  - `Reason`
  - `Description`
  - `Operator`
  - `Workcenter`
- Dashboard reads `Downtime`, normalizes it, and backfills missing workcenters from nearby scan/production data when needed.

### 4. Dashboard refresh flow

- `DataStore.refresh()` reads Google Sheets:
  - `Sheet1`
  - `Scans`
  - `Production`
  - `Downtime`
  - `Products`
- Dashboard normalizes timestamps, cycle times, workcenters, downtime reasons, and expected cycle values.
- `update_all()` and `_update_all_impl()` filter by date/workcenter/product/time window and produce:
  - KPI cards
  - OEE metrics
  - downtime charts
  - output charts
  - registered stop tables

## Identified Critical Risk Areas

- Import-time Google Sheets authentication in `Fluidra_Manufacturing_Solutionv7.4.py`.
  - If credentials/network fail, the logger can fail before the UI is fully usable.
- Dual-write scan behavior to both `Scans` and legacy `Sheet1`.
  - This is clearly relied on by downstream logic and was preserved.
- Excel network/local fallback.
  - If the network path is unavailable, logs shift to a local file and data can diverge until resynced.
- Barcode duplicate detection is multi-source and stateful.
  - It depends on local Excel state, in-memory caches, and live Google Sheets lookups.
- Single-file logger design.
  - The logger contains UI, barcode handling, Excel writes, Google Sheets writes, printer code, schedule logic, and downtime logic in one file.
- Dashboard calculations depend on tolerant schema detection.
  - Column matching is heuristic and intended to support legacy variations.
- Downtime workcenter backfill is inferential.
  - Missing workcenters are derived from surrounding events, which is useful but sensitive.
- OEE and scheduled-break logic are encoded directly in dashboard calculation helpers.
  - Any future renames or schema edits could silently change KPI meaning.
- Printer and Teraoka are hard runtime edges.
  - Printer availability and Teraoka connectivity affect live operator workflows.

## Assumptions

- `Fluidra_Manufacturing_Solutionv7.4.py` is the active logger entry file.
  - This is based on current modification timestamps and `build_fms.py` targeting that file.
- `plant_dashboard.py` is the active dashboard entry file.
- The system is running on Windows, so case differences like `Terioka_config.json` vs `terioka_config.json` are currently tolerated by the filesystem.
- Google Sheets workbook name remains `Production Log`.
- Current sheet names in live use are:
  - `Sheet1`
  - `Scans`
  - `Products`
  - `Production`
  - `Downtime`

## What Changed In This Phase

- Added shared logging helper: `fms_logging.py`.
- Added startup logs for logger and dashboard bootstrap paths.
- Added critical error logging around:
  - Google Sheets init/read/append/find paths
  - Excel init/write/sync paths
  - printer status/preview/label print paths
  - dashboard refresh and callback refresh paths

## What Was Explicitly Not Changed Yet

- No sheet names were renamed.
- No column names were renamed.
- No event names were renamed.
- No business rules were changed for:
  - duplicate barcode detection
  - production start/stop
  - downtime thresholds
  - dashboard KPI calculations
  - printer quantity behavior
  - Google Sheets append patterns
- No UI redesign was done.
- No schema migration was done.
- No legacy `Sheet1` behavior was removed.
- No Teraoka workflow behavior was removed.
- No broad refactor was performed.
