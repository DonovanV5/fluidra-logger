# HEALTH SIGNALS

## Shared Health States

The shared health-state vocabulary now lives in `fms_logging.py`:

- `OK`
- `WARNING`
- `ERROR`
- `UNKNOWN`

These states are used by both the logger and dashboard.

## Logger Health Signals

File: `Fluidra_Manufacturing_Solutionv7.4.py`

### `google_sheets`

- Where set:
  - `_seed_health_signals()`
  - `_append_map_to_sheet()`
  - `initialize_excel_log()`
  - `sync_all_to_google_sheets()`
  - `sync_to_google_sheets()`
  - `_async_log_scan()`
- Where displayed:
  - Main operator screen `info_frame` via `integration_health_var`
- Meaning:
  - `OK`: Google Sheets connection/write path is currently succeeding.
  - `WARNING`: non-fatal Google Sheets degradation such as header fallback or barcode-seed degradation.
  - `ERROR`: critical Google Sheets read/write failure.
  - `UNKNOWN`: no meaningful runtime status yet.

### `excel`

- Where set:
  - `_seed_health_signals()`
  - logger startup network/local path selection
  - `initialize_excel_log()`
  - `log_scan_to_excel()`
  - `_async_log_scan()`
- Where displayed:
  - Main operator screen `info_frame` via `integration_health_var`
- Meaning:
  - `OK`: Excel file initialized/read/written successfully on the preferred path.
  - `WARNING`: Excel is working, but the logger is using the local fallback path instead of the network location.
  - `ERROR`: Excel init/read/write request failed.
  - `UNKNOWN`: Excel path not verified yet.

### `printer`

- Where set:
  - `_seed_health_signals()`
  - `update_printer_status()`
  - `_is_printer_available()`
  - `print_preview()`
  - `print_label()`
- Where displayed:
  - Existing printer status label
  - Main operator screen `info_frame` via `integration_health_var`
- Meaning:
  - `OK`: printer is ready or a label/test print was queued successfully.
  - `WARNING`: printer unavailable, offline, or not ready.
  - `ERROR`: printer status polling or print execution failed unexpectedly.
  - `UNKNOWN`: printer not checked yet.

### `teraoka`

- Where set:
  - `_seed_health_signals()`
  - `poll_teraoka_status()`
  - `_load_teraoka_config()`
  - `_switch_workcenter()`
  - `_on_toggle_teraoka()`
  - `handle_scan()` when receipt enqueue fails
- Where displayed:
  - Existing Teraoka status label
  - Main operator screen `info_frame` via `integration_health_var`
- Meaning:
  - `OK`: connected and ready with a job.
  - `WARNING`: disconnected, connecting, waiting for a job, or enqueue/config problems.
  - `ERROR`: status polling or startup/toggle failed.
  - `UNKNOWN`: disabled or not checked yet.

### `scan_write`

- Where set:
  - `_seed_health_signals()`
  - `log_scan_to_excel()`
  - `_async_log_scan()`
- Where displayed:
  - Main operator screen `info_frame` via `write_health_var`
- Meaning:
  - `OK`: last Excel-backed scan write succeeded.
  - `WARNING`: not currently used.
  - `ERROR`: scan logging request or Excel-backed scan write failed.
  - `UNKNOWN`: no scan write has happened yet.

### `google_write`

- Where set:
  - `_seed_health_signals()`
  - `_append_map_to_sheet()`
  - `sync_all_to_google_sheets()`
  - `sync_to_google_sheets()`
  - `_async_log_scan()`
- Where displayed:
  - Main operator screen `info_frame` via `write_health_var`
- Meaning:
  - `OK`: last Google Sheets write succeeded.
  - `WARNING`: not currently used.
  - `ERROR`: startup sync or live worksheet write failed.
  - `UNKNOWN`: no Sheets write has happened yet.

### `duplicate_check`

- Where set:
  - `_seed_health_signals()`
  - `initialize_excel_log()`
  - `_update_barcode_cache()`
  - `is_duplicate_barcode()`
  - `_barcode_exists_in_sheets()`
- Where displayed:
  - Main operator screen `info_frame` via `write_health_var`
- Meaning:
  - `OK`: cache refresh or direct lookup completed successfully.
  - `WARNING`: duplicate-check fallback or cache refresh failed; scans are still allowed by existing legacy behavior.
  - `ERROR`: not currently used.
  - `UNKNOWN`: no duplicate-check cache/lookup outcome yet.

### Logger Time Signals

- `last_successful_scan_write_at`
  - Set in `_async_log_scan()`
  - Displayed in `write_health_var`
- `last_successful_google_write_at`
  - Set in `_append_map_to_sheet()`, `sync_to_google_sheets()`, `_async_log_scan()`
  - Displayed in `write_health_var`
- `last_duplicate_check_failure_at`
  - Set in `_update_barcode_cache()`, `is_duplicate_barcode()`, `_barcode_exists_in_sheets()`
  - Displayed in `write_health_var`

## Dashboard Health Signals

File: `plant_dashboard.py`

### `google_sheets`

- Where set:
  - `_seed_health_signals()`
  - `_init_gsheets()`
  - `_reauth()`
  - `_record_read_failure()`
  - `refresh()`
  - `append_product()`
- Where displayed:
  - Header subtitle via `store.health_summary_text()`
- Meaning:
  - `OK`: Sheets auth/reauth is working.
  - `WARNING`: not currently the primary degraded state; read degradation is shown mainly through `refresh`/`sheet_reads`.
  - `ERROR`: init, reauth, or read/write path failed.
  - `UNKNOWN`: dashboard has not yet established Sheets state.

### `sheet_reads`

- Where set:
  - `_seed_health_signals()`
  - `_read_sheet()`
  - `_record_read_failure()`
  - `refresh()`
- Where displayed:
  - Header subtitle via `store.health_summary_text()`
- Meaning:
  - `OK`: all required worksheet reads completed.
  - `WARNING`: refresh reused cached data for one or more failed sheets.
  - `ERROR`: worksheet read failed and the refresh is degraded or unavailable.
  - `UNKNOWN`: no worksheet reads yet.

### `refresh`

- Where set:
  - `_seed_health_signals()`
  - `_init_gsheets()`
  - `_record_read_failure()`
  - `refresh()`
  - `update_all()`
  - `_build_initial_dashboard_payload()`
- Where displayed:
  - Header subtitle via `store.health_summary_text()`
- Meaning:
  - `OK`: dashboard refresh completed without failed sheet reads.
  - `WARNING`: dashboard refreshed with cached data for one or more failed sheet reads.
  - `ERROR`: callback refresh, interval refresh, init, or preload failed.
  - `UNKNOWN`: no refresh completed yet.

### Dashboard Time Signals

- `last_refresh`
  - Meaning: last successful dashboard refresh time
  - Displayed in header subtitle as `Last successful refresh`
- `last_refresh_failure`
  - Meaning: last failed or degraded dashboard refresh time
  - Displayed in header subtitle as `Last Fail`
- `last_refresh_failure_detail`
  - Meaning: latest failure/degradation reason
  - Displayed in header subtitle as `Refresh issue: ...`
- `last_successful_google_read`
  - Meaning: last successful worksheet read time
  - Tracked internally for diagnosis

## Display Locations Summary

- Logger:
  - Main operator screen `info_frame`
  - `integration_health_var` line
  - `write_health_var` line
  - Existing printer and Teraoka labels remain in place
- Dashboard:
  - Existing header subtitle line
  - No dashboard layout redesign was introduced

## Manual Verification Checklist

### Google Sheets disconnected

- Launch logger/dashboard with invalid credentials path or disconnected network access to Google Sheets.
- Confirm logger health line shows `Sheets ERROR` or `Sheets WARNING`.
- Confirm dashboard subtitle shows refresh/read error instead of implying a normal zero-production state.
- Confirm dashboard subtitle shows `Last successful refresh` separately from `Last Fail`.

### Printer unavailable

- Disconnect or disable the Zebra/default printer.
- Confirm logger printer line still updates.
- Confirm logger health line shows `Printer WARNING` or `Printer ERROR`.
- Attempt a print and confirm the warning/error is visible and logged.

### Teraoka unavailable

- Enable Teraoka with the service unavailable or wrong endpoint.
- Confirm logger shows Teraoka degraded state without changing scan workflow rules.
- Confirm logger health line shows `Teraoka WARNING` or `Teraoka ERROR`.

### Dashboard refresh failure

- Break worksheet access after a successful dashboard load.
- Confirm the header subtitle shows cached/degraded refresh state.
- Confirm failed reads do not silently become a clean idle state.

### Excel write failure

- Make `barcode_log.xlsx` unavailable or read-only.
- Scan a barcode.
- Confirm logger health line shows `Excel ERROR` and `Scan ERROR`.
- Confirm the failure is logged in the structured log files.
