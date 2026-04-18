# Threading Model

## Background Workers
- Scan persistence worker
  - Started by `log_scan_to_excel(...)` in [`Fluidra_Manufacturing_Solutionv7.4.py`](C:/Developments/Fluidra_Manufacturing%20Solution/Fluidra_Manufacturing_Solutionv7.4.py)
  - Executes `_async_log_scan(...)`
  - Performs Excel and Google Sheets persistence only
- Duplicate-cache refresh worker
  - Started on demand by `is_duplicate_barcode(...)`
  - Executes `_update_barcode_cache(...)`
  - Refreshes duplicate lookup cache from Google Sheets
- Teraoka client worker
  - Lives inside [`teraoka_client.py`](C:/Developments/Fluidra_Manufacturing%20Solution/teraoka_client.py)
  - Handles connection/login/job refresh and queued receipt submission
- Tk timer callbacks on main thread
  - `poll_printer_status(...)`
  - `poll_teraoka_status(...)`
  - `check_production_schedule(...)`
  - `update_time(...)`
  - `update_production_timer(...)`
  - `update_live_labels(...)`

## Main-Thread-Only Sections
- All Tk widgets and windows
- All Tk variables such as `StringVar` and `BooleanVar`
- Health summary rendering:
  - `integration_health_var`
  - `write_health_var`
  - health label color updates
- Operator-visible flow:
  - scan acceptance UI updates
  - duplicate popup actions
  - production start/stop
  - downtime popups
  - printer and Teraoka status label updates
- Production schedule evaluation now runs on the Tk main thread only

## Queues, Callbacks, And Helpers Introduced
- `_ui_task_queue`
  - Worker-to-main-thread handoff queue for Tk-visible updates
- `_schedule_ui_dispatch_pump()`
  - Starts the recurring Tk-side queue pump
- `_process_ui_dispatch_queue()`
  - Runs queued callbacks on the main thread
- `_is_ui_thread()`
  - Identifies whether code is already running on the Tk thread
- `_set_health_signal(...)`
  - Now marshals worker-thread health updates back to the main thread
- `_set_health_timestamp(...)`
  - Marshals UI-visible health timestamps such as:
    - `last_successful_google_write_at`
    - `last_duplicate_check_failure_at`
- `_set_scan_write_health(...)`
  - Marshals scan-write health and `last_successful_scan_write_at`
- `_schedule_next_production_check(...)`
  - Replaces the old scheduler thread with a Tk `after(...)` loop

## Rules For UI And Health Updates
- Background worker code must not directly call:
  - widget `.configure(...)`
  - Tk variable `.set(...)`
  - health-summary refresh methods that touch Tk
- Background worker code may:
  - log structured events
  - perform Excel / Google Sheets I/O
  - update duplicate-cache data structures under `_barcode_cache_lock`
- When worker code needs to affect operator-visible health state, it must use:
  - `_set_health_signal(...)`
  - `_set_health_timestamp(...)`
  - `_set_scan_write_health(...)`
- Production schedule checks must stay on the main thread because they read Tk variables and may call `start_production(...)` / `stop_production(...)`

## Race Conditions Removed
- Dedicated scheduler thread no longer reads Tk variables or starts/stops production from outside the main thread
- Async scan persistence no longer updates health summary state directly from the worker thread
- Duplicate-cache refresh failures no longer update health timestamps from a worker thread directly
- Duplicate-check in-memory state now uses `_barcode_cache_lock` for shared cache/set updates used by both UI and worker code

## Remaining Limitations Intentionally Deferred
- Startup still performs some synchronous initialization and sync work on the main thread to preserve current startup behavior
- `teraoka_client.py` still maintains its own worker thread internally; the logger only polls it from the main thread
- This phase does not redesign the overall worker architecture, replace threads with executors, or change Excel/Google Sheets durability ordering
