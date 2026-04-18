import customtkinter as ctk
from tkinter import messagebox, filedialog
from datetime import datetime, timedelta
import time
import threading
import traceback
import csv
import os
import queue
import subprocess
import platform
import sys
import logging
import logging.handlers
import glob
import re
import socket
import zipfile
from tkinter import Toplevel, StringVar
from startup_self_checks import (
    StartupCheckResult,
    check_directory,
    check_google_workbook_access,
    check_optional_json_file,
    check_printer_target,
    check_required_file,
    check_sqlite_target,
    check_teraoka_readiness,
    summarize_startup_checks,
)
import json
from fms_logging import (
    HEALTH_ERROR,
    HEALTH_OK,
    HEALTH_UNKNOWN,
    HEALTH_WARNING,
    configure_app_logger,
    elapsed_ms,
    get_log_context,
    health_state_color,
    log_event,
    log_timing,
    make_correlation_id,
    set_health_signal,
    set_log_context,
    structured_message,
)
from schema_contract import (
    DOWNTIME_HEADERS,
    PRODUCT_LOOKUP_COLUMNS,
    PRODUCTION_EVENT_END,
    PRODUCTION_EVENT_START,
    PRODUCTION_HEADERS,
    SCAN_HEADERS,
    SCAN_STATUS_REWORKED,
    SCAN_STATUS_SCANNED,
    SHEET_DOWNTIME,
    SHEET_PRODUCTS,
    SHEET_PRODUCTION,
    SHEET_SCANS,
    SHEET_SCANS_LEGACY,
    build_downtime_row,
    build_production_row,
    build_scan_row,
    format_contract_timestamp,
    normalize_scan_records,
    normalize_scan_status,
)
from persistence.excel_export_service import build_export_dataframe, style_excel_export_sheet
from persistence.google_sync_service import (
    build_sheet_row,
    format_sheet_row_ref,
    normalize_sheet_text,
    resolve_sheet_value,
    sheet_row_matches_payload,
)
from persistence.local_store_service import create_local_event_store
from persistence.server_csv_service import (
    read_csv_records,
    server_csv_path,
    server_csv_root_dir,
    server_csv_station_dir,
    server_product_csv_path,
    server_product_csv_paths,
    write_rows_to_csv_atomic,
)
from services.diagnostics_service import (
    diagnostics_metadata as build_diagnostics_metadata,
    format_health_details as build_health_details_text,
    read_redacted_json_file,
    redact_diagnostics_data,
)
from services.downtime_service import (
    build_downtime_event_row,
    coerce_auto_downtime_multiplier,
    format_auto_downtime_multiplier,
    resume_button_enabled,
)
from services.duplicate_service import duplicate_cache_lookup, should_refresh_barcode_cache
from services.health_service import format_health_display_texts
from services.print_audit_service import (
    append_print_audit_record,
    build_print_audit_record,
    format_print_audit_rows,
    print_audit_outcome_is_success,
    read_recent_print_audit,
)
from services.printer_service import (
    code128_patterns,
    coerce_print_quantity,
    extract_zpl_dimensions_mm,
    fit_preview_image,
    format_label_dimension,
    load_zpl_preset_names as load_zpl_preset_names_from_dirs,
    prepare_zpl_print_job,
    printer_is_available,
    resolve_zpl_file_path,
    resolve_zpl_preset_path,
    sanitize_zpl_payload,
    send_raw_printer_job,
    upsert_zpl_size_metadata,
    validate_zpl_template,
    zpl_command_tokens,
    zpl_preset_paths,
)
from services.production_service import (
    build_production_event_row,
    calculate_pcs_per_min,
    calculate_production_duration,
)
from services.scan_service import calculate_scan_cycle_time, normalize_barcode
from services.schedule_service import (
    active_planned_break_window,
    default_production_schedule,
    get_production_schedule_mtime,
    get_schedule_for_workcenter,
    load_production_schedule_config,
    normalize_production_schedule,
    normalize_production_schedule_config,
    normalize_workcenter_selection,
)
from services.teraoka_service import (
    load_teraoka_config as load_teraoka_config_file,
    read_teraoka_status,
    shutdown_teraoka_client,
    start_teraoka_client,
)
from ui.startup_screen import StartupScreen
from ui.status_dialog import create_status_logs_dialog
from ui.window_utils import (
    current_monitor_geometry,
    format_window_geometry,
    present_app_dialog,
    scaled_dim,
    scaled_font,
    set_label_color,
    set_textbox_value,
    tk_attribute_enabled,
)
from utils.formatting_utils import parse_expected_cycle
from utils.path_utils import get_base_path

win32print = None
gspread = None
ServiceAccountCredentials = None
Image = None
pd = None
PatternFill = None
LocalEventStore = None
TeraokaClient = None


# Get the base path for the application
BASE_PATH = get_base_path(__file__)
LOGGER = configure_app_logger("FluidraApp", "production.log", BASE_PATH)
APP_RUN_ID = make_correlation_id("run")
APP_HOSTNAME = socket.gethostname()
set_log_context(app_run_id=APP_RUN_ID, host=APP_HOSTNAME)
ZPL_PRESETS_DIR = os.path.join(BASE_PATH, 'zpl_presets')
os.makedirs(ZPL_PRESETS_DIR, exist_ok=True)  # Ensure the directory exists


def _resolve_workcenter_config_path() -> str:
    candidates = [
        os.path.join(BASE_PATH, 'config', 'terioka_config.json'),
        os.path.join(BASE_PATH, 'config', 'Terioka_config.json'),
        os.path.join(BASE_PATH, 'config', 'workcenters.json'),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# --- CONFIGURATION ---
SHEET_NAME = "Production Log"
PRODUCT_SHEET = SHEET_PRODUCTS
LABEL_WIDTH = 100  # mm
LABEL_HEIGHT = 150  # mm
ZEBRA_PRINTER_NAME = "ZDesigner ZD220-203dpi ZPL"
TERAOKA_WSDL_URL = "http://10.61.6.30:9084/Teraoka_Manufacturing_Web_Service.svc?wsdl"
TERAOKA_WORKCENTER = "Q-PP"
TERAOKA_SUPERVISOR = "1019"
TERAOKA_CONFIG_PATH = _resolve_workcenter_config_path()
USER_PREFS_PATH = os.path.join(BASE_PATH, 'config', 'user_prefs.json')
GOOGLE_CREDENTIALS_FILE = os.path.join(BASE_PATH, "pumpline-logger.json")
PRODUCTION_SCHEDULE_FILE = os.path.join(BASE_PATH, "config", "production_schedule.json")
LOG_BACKEND_GOOGLE = "Google Sheets"
LOG_BACKEND_SERVER_CSV = "Server CSV"
LOG_BACKEND_BOTH = "Both"
LOG_BACKEND_OPTIONS = [LOG_BACKEND_GOOGLE, LOG_BACKEND_SERVER_CSV, LOG_BACKEND_BOTH]
SERVER_CSV_FILENAMES = {
    SHEET_SCANS: "scans.csv",
    SHEET_PRODUCTION: "production.csv",
    SHEET_DOWNTIME: "downtime.csv",
}
SERVER_PRODUCT_HEADERS = ["Product Code", "Description", "Expected Cycle", "Barcode Display"]
# Transport metadata column for idempotent downstream sync. This is additive and
# intentionally kept outside the canonical business-field contract.
SYNC_EVENT_ID_HEADER = "Sync Event ID"
PRINT_AUDIT_HEADERS = [
    "Timestamp",
    "Job Type",
    "Barcode",
    "Status",
    "Quantity",
    "Printer",
    "Preset",
    "Product Code",
    "Workcenter",
    "Outcome",
    "Error",
]
ZPL_ALLOWED_PLACEHOLDERS = {
    "Barc",
    "PC",
    "barcode_text",
    "batch_code",
    "desc1",
    "desc2",
    "description",
    "height_dots",
    "timestamp",
    "width_dots",
}
PLANNED_BREAK_DEFINITIONS = (
    ("Tea 1", "tea1_start", "tea1_end"),
    ("Lunch", "lunch_start", "lunch_end"),
    ("Tea 2", "tea2_start", "tea2_end"),
)


def _default_production_schedule():
    return default_production_schedule()


def _normalize_production_schedule(data):
    return normalize_production_schedule(data)


def _normalize_production_schedule_config(data):
    return normalize_production_schedule_config(data)


def _load_production_schedule_config():
    return load_production_schedule_config(PRODUCTION_SCHEDULE_FILE)


def _get_schedule_for_workcenter(schedule_config, workcenter):
    return get_schedule_for_workcenter(schedule_config, workcenter)


def _load_user_prefs_file():
    try:
        if os.path.exists(USER_PREFS_PATH):
            with open(USER_PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        LOGGER.exception(structured_message("user_prefs_load_failed", path=USER_PREFS_PATH))
    return {}


def _normalize_logging_backend(value):
    normalized = str(value or LOG_BACKEND_GOOGLE).strip().lower()
    if normalized in {"server", "server csv", "csv", "server_csv"}:
        return LOG_BACKEND_SERVER_CSV
    if normalized in {"both", "google+server", "google and server", "server and google"}:
        return LOG_BACKEND_BOTH
    return LOG_BACKEND_GOOGLE


ENABLE_LEGACY_DATAFRAME_SYNC_WRAPPER = True

# --- GOOGLE SHEETS CLIENTS ---
GOOGLE_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
client = None
sheet = None
product_sheet = None
downtime_sheet = None


def _status_update(status_callback, message):
    if status_callback is None:
        return
    try:
        status_callback(message)
    except Exception:
        pass


def load_startup_dependencies(status_callback=None):
    """Load heavier modules after the visible startup dialog is on screen."""
    global win32print, Image, pd, PatternFill, LocalEventStore

    if win32print is None:
        _status_update(status_callback, "Loading printer support...")
        import win32print as _win32print

        win32print = _win32print

    if pd is None:
        _status_update(status_callback, "Loading data tools...")
        import pandas as _pd

        pd = _pd

    if PatternFill is None:
        from openpyxl.styles import PatternFill as _PatternFill

        PatternFill = _PatternFill

    if Image is None:
        _status_update(status_callback, "Loading image support...")
        from PIL import Image as _Image

        Image = _Image

    if LocalEventStore is None:
        _status_update(status_callback, "Loading local storage...")
        from local_event_store import LocalEventStore as _LocalEventStore

        LocalEventStore = _LocalEventStore


def load_google_dependencies(status_callback=None):
    global gspread, ServiceAccountCredentials

    if gspread is None:
        _status_update(status_callback, "Loading Google Sheets support...")
        import gspread as _gspread

        gspread = _gspread

    if ServiceAccountCredentials is None:
        from oauth2client.service_account import ServiceAccountCredentials as _ServiceAccountCredentials

        ServiceAccountCredentials = _ServiceAccountCredentials


def load_teraoka_client():
    global TeraokaClient

    if TeraokaClient is None:
        from teraoka_client import TeraokaClient as _TeraokaClient

        TeraokaClient = _TeraokaClient
    return TeraokaClient


def initialize_google_sheets():
    """Connect to Google Sheets after the startup screen has been painted."""
    global client, sheet, product_sheet, downtime_sheet

    if sheet is not None and product_sheet is not None and downtime_sheet is not None:
        return

    started_at = time.perf_counter()
    load_google_dependencies()

    credentials_check = check_required_file(
        GOOGLE_CREDENTIALS_FILE,
        "Google credentials",
        guidance="Restore the service-account JSON before starting the logger.",
    )
    if credentials_check.state == HEALTH_ERROR:
        LOGGER.error(
            structured_message(
                "startup_required_file_missing",
                check=credentials_check.name,
                detail=credentials_check.detail,
                path=GOOGLE_CREDENTIALS_FILE,
            )
        )
        raise FileNotFoundError(credentials_check.detail)

    try:
        log_event(
            LOGGER,
            logging.INFO,
            "google_sheets_init_start",
            credentials=GOOGLE_CREDENTIALS_FILE,
            workbook=SHEET_NAME,
        )
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME)
        product_sheet = sheet.worksheet(PRODUCT_SHEET)
        downtime_sheet = (
            sheet.worksheet("Downtime")
            if "Downtime" in [ws.title for ws in sheet.worksheets()]
            else sheet.add_worksheet(title="Downtime", rows="1000", cols="10")
        )
        log_event(
            LOGGER,
            logging.INFO,
            "google_sheets_init_complete",
            worksheets=[PRODUCT_SHEET, "Downtime"],
            duration_ms=elapsed_ms(started_at),
        )
    except Exception:
        LOGGER.exception(
            structured_message(
                "google_sheets_init_failed",
                credentials=GOOGLE_CREDENTIALS_FILE,
                workbook=SHEET_NAME,
                duration_ms=elapsed_ms(started_at),
                action="Check the credentials file path, Google sharing permissions, and workbook availability.",
            )
        )
        raise


def get_product_info(product_code):
    initialize_google_sheets()
    product_data = product_sheet.get_all_values()
    for row in product_data[1:]:
        product_code_index = PRODUCT_LOOKUP_COLUMNS["Product Code"]
        description_index = PRODUCT_LOOKUP_COLUMNS["Description"]
        expected_cycle_index = PRODUCT_LOOKUP_COLUMNS["Expected Cycle"]
        barcode_display_index = PRODUCT_LOOKUP_COLUMNS["Barcode Display"]
        if row[product_code_index].strip().lower() == product_code.strip().lower():
            # Handle Expected Cycle safely
            expected_str = row[expected_cycle_index] if len(row) > expected_cycle_index else "0"
            expected_str = expected_str.replace(',', '.')  # convert comma to dot
            try:
                expected_cycle = float(expected_str)
                expected_cycle_display = f"{expected_cycle:.2f} sec"
            except ValueError:
                expected_cycle = 0
                expected_cycle_display = "N/A"

            return {
                "description": row[description_index] if len(row) > description_index else "",
                "Barc": row[barcode_display_index] if len(row) > barcode_display_index else "",
                "PC": row[product_code_index] if len(row) > product_code_index else "",
                "Expected_Cycle": expected_cycle_display
            }
    return None

class BarcodeApp(ctk.CTk):
    # Software version
    VERSION = "FMS v7.10"
    SCAN_CAPTURE_MIN_LENGTH = 6
    SCAN_CAPTURE_IDLE_MS = 120
    SCAN_CAPTURE_MAX_KEY_GAP_SECONDS = 0.25
    MAIN_WINDOW_MIN_WIDTH = 1024
    MAIN_WINDOW_MIN_HEIGHT = 700
    
    def get_zpl_file_path(self, filename):
        """
        Get the path to a ZPL file, working both in development and when packaged.
        """
        return resolve_zpl_file_path(filename, getattr(self, 'custom_zpl_presets_dir', None), ZPL_PRESETS_DIR)
    
    def __init__(self):
        self._startup_perf = time.perf_counter()
        super().__init__()
        self.withdraw()
        self._ui_thread_id = threading.get_ident()
        self._ui_task_queue = queue.Queue()
        self._ui_dispatch_running = True
        self._ui_dispatch_after_id = None
        self._production_schedule_after_id = None
        self._shutdown_requested = False
        self._main_kiosk_enabled = True
        self._main_topmost_enabled = True
        self._taskbar_hidden_by_app = False
        try:
            import atexit
            atexit.register(self._restore_windows_taskbar)
        except Exception:
            pass
        self.health_signals = {}
        self.integration_health_var = ctk.StringVar(value="Health: initializing...")
        self.write_health_var = ctk.StringVar(value="Writes: Scan -- | Sheets -- | Dup fail --")
        self.integration_health_label = None
        self.write_health_label = None
        self.last_successful_scan_write_at = None
        self.last_successful_google_write_at = None
        self.last_successful_server_csv_write_at = None
        self.last_duplicate_check_failure_at = None
        self.local_store = None
        self.local_db_file = ""
        self.print_audit_file = os.path.join(BASE_PATH, "data", "print_audit.csv")
        self._print_audit_lock = threading.Lock()
        self.last_print_record = None
        self.last_label_context = None
        self.startup_checks = []
        self._excel_path_fallback_active = False
        self.local_path = os.path.dirname(os.path.abspath(__file__))
        self._startup_prefs = _load_user_prefs_file()
        self.logging_backend = _normalize_logging_backend(self._startup_prefs.get("logging_backend"))
        self.server_csv_dir = str(self._startup_prefs.get("server_csv_dir", "") or "").strip()
        self._server_csv_lock = threading.Lock()
        self._seed_health_signals()
        self._schedule_ui_dispatch_pump()
        self._install_kiosk_shortcuts()
        log_event(
            LOGGER,
            logging.INFO,
            "app_startup_begin",
            version=self.VERSION,
            base_path=BASE_PATH,
            logging_backend=self.logging_backend,
            server_csv_configured=bool(self.server_csv_dir),
        )
        
        # Create and show startup screen
        self.startup_screen = StartupScreen(self)
        self.startup_screen.update_status("Initializing application...")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.startup_screen.tkraise()
        
        # Force multiple updates to ensure startup screen is visible
        self.startup_screen.update()
        self.startup_screen.update_idletasks()
        self.update()
        self.update_idletasks()
        
        # Small delay to ensure startup screen is fully rendered
        time.sleep(0.2)
        
        load_startup_dependencies(self.startup_screen.update_status)
        if self._logging_backend_uses_google():
            self.startup_screen.update_status("Connecting to Google Sheets...")
            try:
                initialize_google_sheets()
            except Exception:
                self._set_health_signal("google_sheets", HEALTH_ERROR, "Google init failed")
                self._set_health_signal("google_write", HEALTH_ERROR, "Google init failed")
                if getattr(self, "logging_backend", LOG_BACKEND_GOOGLE) == LOG_BACKEND_GOOGLE:
                    raise
                LOGGER.exception(structured_message("google_sheets_init_failed_nonblocking", logging_backend=self.logging_backend))
        else:
            self.startup_screen.update_status("Google Sheets disabled by logging backend...")
            self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Disabled by logging backend")
            self._set_health_signal("google_write", HEALTH_UNKNOWN, "Disabled by logging backend")

        # Excel logging - try network location first, fall back to local directory
        self.startup_screen.update_status("Setting up logging...")
        self.network_path = r"\\whjhbfil02\Shared\Share Engineering\Engineering Share\Pumps Line"
        
        # ZPL presets directory (can be overridden by user)
        self.zpl_presets_dir = ZPL_PRESETS_DIR
        self.custom_zpl_presets_dir = None  # Will be set if user selects a custom directory
        
        # Ensure the ZPL presets directory exists
        if not os.path.exists(self.zpl_presets_dir):
            os.makedirs(self.zpl_presets_dir)
        
        try:
            if os.path.exists(self.network_path):
                self.excel_file = os.path.join(self.network_path, "barcode_log.xlsx")
                print(f"Using network location for logs: {self.excel_file}")
                log_event(LOGGER, logging.INFO, "excel_log_path_selected", location="network", path=self.excel_file)
            else:
                self.excel_file = os.path.join(self.local_path, "barcode_log.xlsx")
                print(f"Network location not available. Using local path: {self.excel_file}")
                log_event(LOGGER, logging.INFO, "excel_log_path_selected", location="local_fallback", path=self.excel_file)
                self._excel_path_fallback_active = True
                self._set_health_signal("excel", HEALTH_WARNING, "Using local fallback path")
        except Exception as e:
            self.excel_file = os.path.join(self.local_path, "barcode_log.xlsx")
            print(f"Error accessing network path. Using local path: {self.excel_file}")
            print(f"Error details: {e}")
            self._excel_path_fallback_active = True
            self._set_health_signal("excel", HEALTH_WARNING, "Using local fallback path")
            LOGGER.exception(
                structured_message(
                    "excel_log_path_resolution_failed",
                    network_path=self.network_path,
                    fallback_path=self.excel_file,
                )
            )

        self.startup_screen.update_status("Initializing local event store...")
        self.local_db_file = os.path.join(self.local_path, "data", "fms_local_store.sqlite3")
        self.initialize_local_store()

        self.initialize_excel_log()
        
        # Sync existing data to the selected downstream target(s) on startup
        self.startup_screen.update_status("Syncing data to selected logging target...")
        self.sync_all_to_google_sheets()

        # Variables
        self.product_var = ctk.StringVar()
        self.barcode_var = ctk.StringVar()
        self.last_scanned_var = ctk.StringVar()
        self.cycle_time_var = ctk.StringVar(value="0.00 s")
        self.time_var = ctk.StringVar()
        self.runtime_var = ctk.StringVar(value="00:00:00")
        self.description_var = ctk.StringVar()
        self.expected_cycle_var = ctk.StringVar(value="N/A")
        self.production_count_var = ctk.StringVar(value="0")
        self.production_state_var = ctk.StringVar(value="STOPPED")
        self.production_timer_var = ctk.StringVar(value="00:00:00")
        self.pcs_min_var = ctk.StringVar(value="0.00")
        self.operator_name_var = ctk.StringVar()
        self.printer_status_var = ctk.StringVar()
        self.teraoka_status_var = ctk.StringVar()
        self.teraoka_job_var = ctk.StringVar()
        self.teraoka_product_var = ctk.StringVar()
        self.teraoka_quantity_var = ctk.StringVar()
        self.teraoka_required_quantity_var = ctk.StringVar()
        self.teraoka_qty_made_var = ctk.StringVar()
        self.current_cycle_timer_var = ctk.StringVar(value="0.00 s")
        self.PC_var = ctk.StringVar()
        self.downtime_timer_var = ctk.StringVar(value="00:00:00")
        self.workcenter_var = ctk.StringVar()
        self.barcode_label_var = ctk.StringVar()  # For displaying barcode from Google Sheets
        
        # Barcode cache variables
        self._barcode_cache = set()
        self._barcode_cache_lock = threading.Lock()
        self._barcode_cache_ttl = 300  # 5 minutes
        self._barcode_cache_last_update = 0
        self._last_barcode_check = None
        self._last_barcode_result = False
        self._stop_cache_update = threading.Event()
        self._pending_scan_after_id = None
        self._scan_capture_after_id = None
        self._scan_focus_after_id = None
        self._scan_capture_buffer = ""
        self._scan_capture_last_key_at = 0.0
        self._scanner_capture_installed = False
        self._barcode_trace_suppressed = False
        self._scan_processing = False
        self._active_scan_barcode = None
        self.last_scan_time = None
        self.production_count = 0
        self.production_running = False
        self.start_time = None
        self.total_runtime_seconds = 0
        self.last_update_time = None
        self.in_auto_downtime = False
        self.scanned_barcodes = set()
        self.timestamps = []
        self.cycle_times = []
        self.production_timer_label = None
        self.cycle_time_label = None
        self.pcs_min_label = None
        self.printer_status_label = None
        self.teraoka_status_label = None
        self.printer_status_value_label = None
        self.teraoka_status_value_label = None
        self.teraoka_job_value_label = None
        self.last_scanned_value = None
        self.cycle_value = None
        
        # Auto production variables
        self.auto_prod_enabled = ctk.BooleanVar(value=False)
        self.overtime_enabled = ctk.BooleanVar(value=False)
        self.auto_start_time = ctk.StringVar(value="07:30")
        self.auto_stop_time = ctk.StringVar(value="15:15")
        self.overtime_start_time = ctk.StringVar(value="15:30")
        self.overtime_stop_time = ctk.StringVar(value="17:15")
        self.auto_downtime_multiplier = 2.5
        self.auto_downtime_multiplier_var = ctk.StringVar(value="2.5")
        self._production_schedule_config = _load_production_schedule_config()
        self._production_schedule_mtime = None
        self._active_planned_break_context = None
        
        # Print quantity
        self.print_quantity = 2
        self.print_quantity_var = ctk.StringVar(value=str(self.print_quantity))
        
        # Teraoka client settings
        self.teraoka_wsdl = TERAOKA_WSDL_URL
        self.teraoka_supervisor = TERAOKA_SUPERVISOR
        self.teraoka_admin_pw = "admin"
        self.teraoka_enabled = ctk.BooleanVar(value=False)
        self.workcenters = [
            {"id": TERAOKA_WORKCENTER, "name": TERAOKA_WORKCENTER}
        ]
        self._load_teraoka_config()
        self.current_workcenter = self.workcenters[0]["id"] if self.workcenters else TERAOKA_WORKCENTER
        self._saved_zpl_preset = None
        self._load_user_prefs()
        self._normalize_current_workcenter()
        self._update_log_context()
        self._run_startup_self_checks()

        # Build GUI
        self._apply_main_ui_scaling()
        self.startup_screen.update_status("Building user interface...")
        self.build_gui()
        self.update_time()
        
        self.startup_screen.update_status("Initializing printer...")
        self.poll_printer_status()
        
        self.startup_screen.update_status("Setting up timers...")
        self.update_production_timer()
        self.check_auto_downtime()
        self.update_live_labels()
        
        # Start Teraoka client (only if enabled)
        self.teraoka = None
        self.startup_screen.update_status("Initializing Teraoka client...")
        if self.teraoka_enabled.get():
            try:
                teraoka_client_class = load_teraoka_client()
                self.teraoka = teraoka_client_class(self.teraoka_wsdl, self.current_workcenter, self.teraoka_supervisor)
                self.teraoka.start()
                try:
                    # Poke client to establish login/job immediately (no receipt)
                    self.teraoka.enqueue_receipt(0)
                except Exception:
                    pass
                self.startup_screen.update_status("Teraoka client initialized")
                log_event(
                    LOGGER,
                    logging.INFO,
                    "teraoka_client_initialized",
                    workcenter=self.current_workcenter,
                    wsdl=self.teraoka_wsdl,
                )
            except Exception:
                self.teraoka = None
                self.startup_screen.update_status("Teraoka client initialization failed")
                LOGGER.exception(
                    structured_message(
                        "teraoka_client_init_failed",
                        workcenter=self.current_workcenter,
                        wsdl=self.teraoka_wsdl,
                    )
                )
        else:
            self.startup_screen.update_status("Teraoka client disabled")
            log_event(LOGGER, logging.INFO, "teraoka_client_disabled", workcenter=self.current_workcenter)
        
        # Add version label at the bottom when vertical space allows it.
        if not getattr(self, "_main_ui_compact", False):
            version_frame = ctk.CTkFrame(self, height=self._main_dim(20, minimum=16), fg_color="transparent")
            version_frame.pack(side="bottom", fill="x", pady=(0, 2))
            ctk.CTkLabel(
                version_frame, 
                text=f"{self.VERSION}", 
                font=self._main_font(10, "italic"),
                text_color="gray"
            ).pack(side="right", padx=self._main_dim(10, minimum=6))
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.poll_teraoka_status()
        
        # Start the production schedule checker
        self.startup_screen.update_status("Starting production scheduler...")
        print(f"[DEBUG] Starting production schedule checker...")

        # Production scheduling reads Tk state and may start/stop production, so it must stay
        # on the Tk main thread instead of using a background worker.
        try:
            self._schedule_next_production_check(delay_ms=1000)
            print(f"[DEBUG] Production schedule checker scheduled on Tk main thread")
            self.startup_screen.update_status("Production scheduler started")
            log_event(LOGGER, logging.INFO, "production_scheduler_started")
        except Exception as e:
            print(f"[ERROR] Failed to start production scheduler: {e}")
            self.startup_screen.update_status("Failed to start production scheduler")
            LOGGER.exception(structured_message("production_scheduler_start_failed"))
        
        # Final initialization complete
        self.startup_screen.update_status("Finalizing initialization...")
        log_event(
            LOGGER,
            logging.INFO,
            "app_startup_complete",
            workcenter=self.current_workcenter,
            teraoka_enabled=self.teraoka_enabled.get(),
            duration_ms=elapsed_ms(self._startup_perf),
        )
        # Don't call update() here to avoid interfering with startup screen
        
        # Close startup screen shortly after all initialization is complete.
        self.after(500, self._close_startup_screen)
    
    def _close_startup_screen(self):
        """Close the startup screen and show the main application"""
        if self.startup_screen:
            self.startup_screen.destroy()
            self.startup_screen = None
            self.title("Production Dashboard")
            self.deiconify()
            self._apply_main_window_display_mode()
            self._schedule_scan_focus(force=True, attempts=4)

    @staticmethod
    def _format_window_geometry(width, height, x, y):
        return format_window_geometry(width, height, x, y)

    @staticmethod
    def _tk_attribute_enabled(value):
        return tk_attribute_enabled(value)

    def _get_current_monitor_geometry(self):
        """Return the full monitor bounds for the screen containing this window."""
        return current_monitor_geometry(self)

    def _keep_main_window_front(self):
        if not getattr(self, "_main_topmost_enabled", True):
            return
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _install_kiosk_shortcuts(self):
        for sequence in ("<Control-Shift-F11>", "<Control-Shift-KeyPress-F11>", "<Control-Shift-Key-F11>"):
            try:
                self.bind(sequence, self._toggle_main_kiosk_mode, add="+")
                self.bind_all(sequence, self._toggle_main_kiosk_mode, add="+")
            except Exception:
                LOGGER.exception(structured_message("kiosk_shortcut_bind_failed", sequence=sequence))

    def _present_app_dialog(self, dialog, focus_widget=None, modal=True):
        """Keep app dialogs above the kiosk dashboard and ready for input."""
        present_app_dialog(self, dialog, focus_widget, modal)

    def _set_windows_taskbar_visible(self, visible):
        """Show or hide the Windows taskbar for kiosk mode."""
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.FindWindowExW.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
            ]
            user32.FindWindowExW.restype = wintypes.HWND
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            show_cmd = 5 if visible else 0  # SW_SHOW / SW_HIDE
            changed = False
            for class_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                previous = 0
                while True:
                    hwnd = user32.FindWindowExW(0, previous, class_name, None)
                    if not hwnd:
                        break
                    user32.ShowWindow(hwnd, show_cmd)
                    changed = True
                    previous = hwnd
            if changed:
                self._taskbar_hidden_by_app = not visible
                log_event(
                    LOGGER,
                    logging.INFO,
                    "windows_taskbar_visibility_changed",
                    visible=visible,
                )
            return changed
        except Exception:
            LOGGER.exception(structured_message("windows_taskbar_visibility_change_failed", visible=visible))
            return False

    def _hide_windows_taskbar_for_kiosk(self):
        self._set_windows_taskbar_visible(False)

    def _restore_windows_taskbar(self):
        self._set_windows_taskbar_visible(True)
        self._taskbar_hidden_by_app = False

    def _apply_main_window_display_mode(self):
        self.update_idletasks()
        x, y, width, height = self._get_current_monitor_geometry()
        min_width = min(self.MAIN_WINDOW_MIN_WIDTH, width)
        min_height = min(self.MAIN_WINDOW_MIN_HEIGHT, height)

        try:
            self.state("normal")
        except Exception:
            pass
        self.attributes("-fullscreen", False)
        self.resizable(True, True)
        self.minsize(min_width, min_height)
        self.geometry(self._format_window_geometry(width, height, x, y))

        if self._main_kiosk_enabled:
            self._hide_windows_taskbar_for_kiosk()
        else:
            self._restore_windows_taskbar()
        try:
            self.state("zoomed")
        except Exception:
            pass
        if self._main_topmost_enabled:
            self.attributes("-topmost", True)

        self.lift()
        self.focus_force()
        self.after(250, self._keep_main_window_front)

    def _toggle_main_kiosk_mode(self, event=None):
        self._main_kiosk_enabled = not self._main_kiosk_enabled
        self._main_topmost_enabled = self._main_kiosk_enabled
        if self._main_kiosk_enabled:
            self._apply_main_window_display_mode()
            return "break"

        self.attributes("-fullscreen", False)
        self.attributes("-topmost", False)
        self._restore_windows_taskbar()
        try:
            self.state("zoomed")
        except Exception:
            pass
        self.attributes("-topmost", self._main_topmost_enabled)
        self.lift()
        self.focus_force()
        return "break"

    def _apply_main_ui_scaling(self):
        try:
            _x, _y, width, height = self._get_current_monitor_geometry()
            scale = min(width / 1280.0, height / 1000.0, 1.0)
            scale = max(0.66, scale)
            self._main_ui_scale = scale
            self._main_ui_compact = height <= 950 or width <= 1280 or scale < 0.95
            self._main_ui_screen = (width, height)
            ctk.set_widget_scaling(scale)
            log_event(LOGGER, logging.INFO, "main_ui_scaling_applied", scale=round(scale, 3), width=width, height=height)
        except Exception:
            self._main_ui_scale = 1.0
            self._main_ui_compact = False
            self._main_ui_screen = (1280, 800)
            LOGGER.exception(structured_message("main_ui_scaling_failed"))

    def _main_font(self, size, weight=None):
        scale = float(getattr(self, "_main_ui_scale", 1.0) or 1.0)
        return scaled_font(size, scale, getattr(self, "_main_ui_compact", False), weight)

    def _main_dim(self, value, minimum=1):
        scale = float(getattr(self, "_main_ui_scale", 1.0) or 1.0)
        return scaled_dim(value, scale, minimum)

    def _cancel_scan_capture_callback(self):
        after_id = getattr(self, "_scan_capture_after_id", None)
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except Exception:
            pass
        finally:
            self._scan_capture_after_id = None

    def _widget_belongs_to(self, widget, owner):
        if widget is None or owner is None:
            return False
        current = widget
        for _ in range(8):
            if current is owner:
                return True
            try:
                current = getattr(current, "master", None)
            except Exception:
                current = None
            if current is None:
                return False
        return False

    def _is_text_input_widget(self, widget):
        if widget is None:
            return False
        try:
            if isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox, ctk.CTkComboBox)):
                return True
        except Exception:
            pass
        class_names = {widget.__class__.__name__}
        try:
            class_names.add(widget.winfo_class())
        except Exception:
            pass
        text_input_names = {
            "Entry",
            "Text",
            "TEntry",
            "TCombobox",
            "Spinbox",
            "CTkEntry",
            "CTkTextbox",
            "CTkComboBox",
        }
        return bool(class_names.intersection(text_input_names))

    def _scan_entry_is_ready(self):
        if not getattr(self, "production_running", False):
            return False
        entry = getattr(self, "barcode_entry", None)
        if entry is None:
            return False
        try:
            state = str(entry.cget("state") or "").lower()
            if state == "disabled":
                return False
        except Exception:
            pass
        return True

    def _schedule_scan_focus(self, delay_ms=60, force=False, attempts=1):
        if getattr(self, "_shutdown_requested", False):
            return
        previous_after_id = getattr(self, "_scan_focus_after_id", None)
        if previous_after_id is not None:
            try:
                self.after_cancel(previous_after_id)
            except Exception:
                pass
            self._scan_focus_after_id = None
        try:
            self._scan_focus_after_id = self.after(
                delay_ms,
                lambda: self._refocus_scan_entry(force=force, attempts=attempts),
            )
        except Exception:
            self._refocus_scan_entry(force=force, attempts=attempts)

    def _barcode_entry_focus_target(self):
        entry = getattr(self, "barcode_entry", None)
        return getattr(entry, "_entry", None) or entry

    def _focus_barcode_entry_widget(self, force=False):
        entry = getattr(self, "barcode_entry", None)
        target = self._barcode_entry_focus_target()
        if target is None:
            return False
        try:
            if force:
                try:
                    self.lift()
                    self.focus_force()
                except Exception:
                    pass
                if target is not entry and hasattr(target, "focus_force"):
                    target.focus_force()
                elif hasattr(entry, "focus_force"):
                    entry.focus_force()
                else:
                    target.focus_set()
            else:
                if target is not entry:
                    target.focus_set()
                else:
                    entry.focus_set()
            try:
                target.icursor("end")
            except Exception:
                pass
            return True
        except Exception:
            try:
                entry.focus_set()
                return True
            except Exception:
                return False

    def _refocus_scan_entry(self, force=False, attempts=1):
        self._scan_focus_after_id = None
        if not self._scan_entry_is_ready():
            return False
        entry = getattr(self, "barcode_entry", None)
        try:
            active_grab = self.grab_current()
            if active_grab is not None and active_grab is not self:
                return False
        except Exception:
            pass
        try:
            focused_widget = self.focus_get()
            if (
                not force
                and
                focused_widget is not None
                and not self._widget_belongs_to(focused_widget, entry)
                and self._is_text_input_widget(focused_widget)
            ):
                return False
        except Exception:
            pass
        focused = self._focus_barcode_entry_widget(force=force)
        if force and attempts > 1:
            self._schedule_scan_focus(delay_ms=120, force=True, attempts=attempts - 1)
        return focused

    def _install_scanner_capture(self):
        try:
            if not getattr(self, "_scanner_capture_installed", False):
                self.bind_class("ScannerCapture", "<KeyPress>", self._on_global_scan_keypress, add="+")
                self.bind_all("<KeyPress>", self._on_global_scan_keypress, add="+")
                self._scanner_capture_installed = True
                log_event(LOGGER, logging.INFO, "scanner_capture_installed")
            self._apply_scanner_capture_bindtag(self)
        except Exception:
            LOGGER.exception(structured_message("scanner_capture_install_failed"))

    def _apply_scanner_capture_bindtag(self, widget):
        if widget is None:
            return
        try:
            tags = tuple(widget.bindtags())
            if "ScannerCapture" not in tags:
                widget.bindtags(("ScannerCapture", *tags))
        except Exception:
            pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._apply_scanner_capture_bindtag(child)

    def _global_scan_capture_allowed(self):
        if not self._scan_entry_is_ready():
            return False
        if getattr(self, "_scan_processing", False):
            return False
        entry = getattr(self, "barcode_entry", None)
        try:
            active_grab = self.grab_current()
            if active_grab is not None and active_grab is not self:
                return False
        except Exception:
            pass
        focused_widget = None
        try:
            focused_widget = self.focus_get()
        except Exception:
            pass
        if focused_widget is not None:
            if self._widget_belongs_to(focused_widget, entry):
                return False
            if self._is_text_input_widget(focused_widget):
                return False
        return True

    def _reset_scan_capture_buffer(self):
        self._scan_capture_buffer = ""
        self._scan_capture_last_key_at = 0.0

    def _flush_scan_capture_buffer(self, source="idle"):
        after_id = getattr(self, "_scan_capture_after_id", None)
        self._scan_capture_after_id = None
        if after_id is not None and source != "idle":
            try:
                self.after_cancel(after_id)
            except Exception:
                pass

        barcode = str(getattr(self, "_scan_capture_buffer", "") or "").strip()
        self._reset_scan_capture_buffer()
        if len(barcode) < self.SCAN_CAPTURE_MIN_LENGTH:
            return False
        return self._submit_captured_scan(barcode, source=source)

    def _submit_captured_scan(self, barcode, source="global_keypress"):
        barcode = str(barcode or "").strip()
        if len(barcode) < self.SCAN_CAPTURE_MIN_LENGTH:
            return False
        if not self._scan_entry_is_ready():
            log_event(
                LOGGER,
                logging.INFO,
                "scanner_capture_ignored_not_ready",
                source=source,
                length=len(barcode),
            )
            return False

        normalized_barcode = self._normalize_barcode(barcode)
        log_event(
            LOGGER,
            logging.INFO,
            "scanner_capture_ready",
            barcode=normalized_barcode,
            source=source,
            length=len(barcode),
        )
        self._set_barcode_entry_value(barcode)
        return self.handle_scan(None, barcode_override=barcode)

    def _on_global_scan_keypress(self, event):
        if not self._global_scan_capture_allowed():
            self._reset_scan_capture_buffer()
            self._cancel_scan_capture_callback()
            return None

        keysym = str(getattr(event, "keysym", "") or "")
        if keysym in ("Return", "KP_Enter", "Tab"):
            if getattr(self, "_scan_capture_buffer", ""):
                self._flush_scan_capture_buffer(source="terminator")
                return "break"
            return None

        char = getattr(event, "char", "") or ""
        if len(char) != 1 or ord(char) < 32:
            return None

        now = time.monotonic()
        last_key_at = float(getattr(self, "_scan_capture_last_key_at", 0.0) or 0.0)
        if last_key_at and (now - last_key_at) > self.SCAN_CAPTURE_MAX_KEY_GAP_SECONDS:
            self._scan_capture_buffer = ""

        self._scan_capture_buffer = f"{getattr(self, '_scan_capture_buffer', '')}{char}"
        self._scan_capture_last_key_at = now

        self._cancel_scan_capture_callback()
        try:
            self._scan_capture_after_id = self.after(
                self.SCAN_CAPTURE_IDLE_MS,
                lambda: self._flush_scan_capture_buffer(source="idle"),
            )
        except Exception:
            self._flush_scan_capture_buffer(source="idle")

        return "break"

    def _on_barcode_changed(self, *args):
        """Handle barcode scan events (triggered on text change)"""
        if getattr(self, "_barcode_trace_suppressed", False):
            return

        barcode = self.barcode_var.get().strip()
        self._cancel_pending_scan_callback()
        # Only process if we have a barcode, production is running, and barcode is long enough
        if barcode and self.production_running and len(barcode) >= 6:  # Minimum barcode length
            # Use after() to process the barcode after a short delay
            # This allows the scanner to finish sending all characters
            self._pending_scan_after_id = self.after(100, self._process_barcode_scan, barcode)
    
    def _process_barcode_scan(self, barcode):
        """Process a complete barcode scan"""
        self._pending_scan_after_id = None
        # Make sure the barcode hasn't changed since we scheduled this
        if self.barcode_var.get().strip() == barcode:
            print(f"Processing barcode: {barcode}")  # Debug log
            log_event(
                LOGGER,
                logging.INFO,
                "scan_trigger_ready",
                barcode=self._normalize_barcode(barcode),
                length=len(barcode),
            )
            self.handle_scan(None, barcode_override=barcode)

    def __del__(self):
        # Signal the cache update thread to stop
        if hasattr(self, '_stop_cache_update'):
            self._stop_cache_update.set()
        if hasattr(self, '_cache_thread'):
            self._cache_thread.join(timeout=2.0)

    def show_onscreen_keyboard(self, event=None):
        """Show the appropriate on-screen keyboard based on the operating system."""
        system = platform.system().lower()
        
        try:
            if system == 'windows':
                # Try TabTip.exe (Windows Touch Keyboard) first
                try:
                    subprocess.Popen(
                        [r'C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True
                    )
                    return
                except (FileNotFoundError, OSError):
                    # Fall back to osk.exe (On-Screen Keyboard)
                    try:
                        subprocess.Popen(
                            ['osk.exe'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=True
                        )
                        return
                    except Exception as e:
                        print(f"Error launching osk.exe: {e}")
            
            elif system == 'linux':
                # Try to use onboard for Linux
                try:
                    subprocess.Popen(
                        ['onboard'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    return
                except Exception as e:
                    print(f"Error launching onboard: {e}")
            
            # Fallback method
            if system == 'windows':
                os.system('start osk.exe')
            
        except Exception as e:
            print(f"Error showing on-screen keyboard: {e}")
            try:
                messagebox.showerror("Keyboard Error", 
                    "Could not open on-screen keyboard. Please use a physical keyboard or enable the on-screen keyboard manually.")
            except:
                pass
    
    def enable_touch_keyboard(self, widget):
        """Enable touch keyboard support for a widget."""
        if not isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox, ctk.CTkComboBox)):
            return
                
        def on_focus_in(event):
            # Only show keyboard for touch/pen events or if no physical keyboard is detected
            # This prevents the keyboard from popping up when using a physical keyboard
            if hasattr(event, 'state'):
                try:
                    # Safely convert event.state to integer if needed
                    if isinstance(event.state, str):
                        # Handle string states that might contain non-numeric characters
                        if event.state.isdigit():
                            state = int(event.state)
                        else:
                            # If state contains non-numeric characters, skip the touch check
                            state = 0
                    elif isinstance(event.state, int):
                        state = event.state
                    else:
                        # For any other type, skip the touch check
                        state = 0
                    
                    if state & 0x100:  # Check for touch/pen event
                        self.show_onscreen_keyboard()
                        return  # Don't check for touch device if we're already showing keyboard
                except (ValueError, TypeError) as e:
                    print(f"Error processing event state: {e}")
                    # Continue with touch device check if state processing fails
            
            # Check if this is likely a touch device by checking for touch support
            try:
                import ctypes
                has_touch = ctypes.windll.user32.GetSystemMetrics(95) > 0  # SM_DIGITIZER
                if has_touch:
                    self.show_onscreen_keyboard()
            except Exception as e:
                print(f"Error checking touch support: {e}")
        
        # Bind focus in event
        widget.bind('<FocusIn>', on_focus_in)

    def _on_close(self):
        log_event(LOGGER, logging.INFO, "app_shutdown_begin")
        self._shutdown_requested = True
        self._ui_dispatch_running = False
        try:
            self._stop_cache_update.set()
        except Exception:
            pass
        for after_attr in (
            "_pending_scan_after_id",
            "_scan_capture_after_id",
            "_scan_focus_after_id",
            "_production_schedule_after_id",
            "_ui_dispatch_after_id",
        ):
            after_id = getattr(self, after_attr, None)
            if after_id is None:
                continue
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
            setattr(self, after_attr, None)
        try:
            if hasattr(self, "teraoka") and self.teraoka:
                self.teraoka.shutdown()
        except Exception:
            pass
        try:
            self._save_user_prefs()
        except Exception:
            pass
        self._restore_windows_taskbar()
        log_event(LOGGER, logging.INFO, "app_shutdown_complete")
        self.destroy()

    def _normalize_barcode(self, b: str) -> str:
        """Normalize barcode for reliable duplicate detection (trim + uppercase)."""
        return normalize_barcode(b)

    def _update_log_context(self):
        set_log_context(
            app_run_id=APP_RUN_ID,
            host=APP_HOSTNAME,
            app_version=self.VERSION,
            workcenter=getattr(self, "current_workcenter", ""),
            logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
        )

    def _logging_backend_uses_google(self):
        return getattr(self, "logging_backend", LOG_BACKEND_GOOGLE) in {LOG_BACKEND_GOOGLE, LOG_BACKEND_BOTH}

    def _logging_backend_uses_server_csv(self):
        return getattr(self, "logging_backend", LOG_BACKEND_GOOGLE) in {LOG_BACKEND_SERVER_CSV, LOG_BACKEND_BOTH}

    def _set_logging_backend(self, backend):
        self.logging_backend = _normalize_logging_backend(backend)
        self._update_log_context()
        if self._logging_backend_uses_google():
            self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Not checked")
            self._set_health_signal("google_write", HEALTH_UNKNOWN, "No Google Sheets writes yet")
        else:
            self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Disabled by logging backend")
            self._set_health_signal("google_write", HEALTH_UNKNOWN, "Disabled by logging backend")
        if self._logging_backend_uses_server_csv():
            self._set_health_signal("server_csv", HEALTH_UNKNOWN, "Not checked")
        else:
            self._set_health_signal("server_csv", HEALTH_UNKNOWN, "Disabled by logging backend")

    def _seed_health_signals(self):
        self._set_health_signal("local_store", HEALTH_UNKNOWN, "Not initialized")
        self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Not checked")
        self._set_health_signal("server_csv", HEALTH_UNKNOWN, "Not checked")
        self._set_health_signal("excel", HEALTH_UNKNOWN, "Not initialized")
        self._set_health_signal("printer", HEALTH_UNKNOWN, "Not checked")
        self._set_health_signal("teraoka", HEALTH_UNKNOWN, "Not checked")
        self._set_health_signal("scan_write", HEALTH_UNKNOWN, "No scan writes yet")
        self._set_health_signal("google_write", HEALTH_UNKNOWN, "No Google Sheets writes yet")
        self._set_health_signal("duplicate_check", HEALTH_UNKNOWN, "No fallback failures")
        self._set_health_signal("print", HEALTH_UNKNOWN, "No print attempts yet")

    def _set_health_signal(self, name, state, detail="", **fields):
        if not self._is_ui_thread():
            self._queue_ui_task(self._set_health_signal, name, state, detail, **fields)
            return None
        signal = set_health_signal(self.health_signals, name, state, detail=detail, **fields)
        self._refresh_health_display()
        return signal

    def _refresh_health_display(self):
        integration_text, writes_text, integration_state, write_state = format_health_display_texts(
            self.health_signals,
            self.last_successful_scan_write_at,
            self.last_successful_google_write_at,
            self.last_successful_server_csv_write_at,
            self.last_duplicate_check_failure_at,
        )
        self.integration_health_var.set(integration_text)

        self.write_health_var.set(writes_text)

        if self.integration_health_label is not None:
            self.integration_health_label.configure(text_color=health_state_color(integration_state))
        if self.write_health_label is not None:
            self.write_health_label.configure(text_color=health_state_color(write_state))

    def _set_excel_health_success(self, detail):
        state = HEALTH_WARNING if self._excel_path_fallback_active else HEALTH_OK
        return self._set_health_signal("excel", state, detail)

    def _set_local_store_health_success(self, detail):
        return self._set_health_signal("local_store", HEALTH_OK, detail)

    def _emit_startup_check(self, result: StartupCheckResult, *, health_signal: str | None = None):
        fields = {
            "check": result.name,
            "state": result.state,
            "detail": result.detail,
        }
        if result.state == HEALTH_OK:
            log_event(LOGGER, logging.INFO, "startup_self_check_ok", **fields)
        elif result.state == HEALTH_WARNING:
            LOGGER.warning(structured_message("startup_self_check_warning", **fields))
        elif result.state == HEALTH_ERROR:
            LOGGER.error(structured_message("startup_self_check_error", **fields))
        else:
            log_event(LOGGER, logging.INFO, "startup_self_check_info", **fields)

        if health_signal is not None:
            self._set_health_signal(health_signal, result.state, result.detail)

    def _check_google_workbook_startup(self):
        if not self._logging_backend_uses_google():
            return StartupCheckResult(
                "Google workbook",
                HEALTH_UNKNOWN,
                "Google Sheets is disabled by the selected logging backend.",
            )
        return check_google_workbook_access(
            sheet,
            workbook_name=SHEET_NAME,
            required_sheets=[PRODUCT_SHEET, SHEET_DOWNTIME],
            on_demand_sheets=[SHEET_SCANS, SHEET_PRODUCTION, SHEET_SCANS_LEGACY],
        )

    def _check_server_csv_startup(self):
        if not self._logging_backend_uses_server_csv():
            return StartupCheckResult(
                "Server CSV directory",
                HEALTH_UNKNOWN,
                "Server CSV is disabled by the selected logging backend.",
            )
        server_dir = str(getattr(self, "server_csv_dir", "") or "").strip()
        if not server_dir:
            return StartupCheckResult(
                "Server CSV directory",
                HEALTH_WARNING,
                "Server CSV is selected but no server directory is configured yet.",
            )
        return check_directory(server_dir, "Server CSV directory", create_if_missing=False)

    def _check_sqlite_startup_readiness(self):
        if self.local_store is None:
            return StartupCheckResult(
                "SQLite local store",
                HEALTH_ERROR,
                f"SQLite local store failed to initialize at {self.local_db_file}. Check permissions, disk space, and file locks.",
            )
        return check_sqlite_target(self.local_db_file)

    def _check_printer_startup_target(self):
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags)
            names = [printer[2] for printer in printers if len(printer) > 2]
        except Exception as exc:
            return StartupCheckResult(
                "Printer target",
                HEALTH_ERROR,
                f"Printer enumeration failed: {exc}. Verify the Windows print spooler and printer drivers.",
            )
        result = check_printer_target(ZEBRA_PRINTER_NAME, names)
        if result.state == HEALTH_OK and not self._is_printer_available(ZEBRA_PRINTER_NAME):
            return StartupCheckResult(
                "Printer target",
                HEALTH_WARNING,
                f"Configured printer '{ZEBRA_PRINTER_NAME}' is installed but not ready. Check power, cable/network connection, and Windows printer status.",
            )
        return result

    def _check_teraoka_startup_readiness(self):
        return check_teraoka_readiness(
            enabled=bool(self.teraoka_enabled.get()),
            config_path=TERAOKA_CONFIG_PATH,
            wsdl_url=self.teraoka_wsdl,
            supervisor=self.teraoka_supervisor,
            workcenter=self.current_workcenter,
        )

    def _run_startup_self_checks(self):
        self.startup_screen.update_status("Running startup self-checks...")
        config_dir = os.path.join(self.local_path, "config")
        data_dir = os.path.dirname(self.local_db_file)
        results: list[tuple[StartupCheckResult, str | None]] = [
            (check_directory(config_dir, "Config directory", create_if_missing=True), None),
            (check_directory(data_dir, "Local data directory", create_if_missing=True), None),
            (check_directory(self.zpl_presets_dir, "ZPL presets directory", create_if_missing=True), None),
            (check_directory(os.path.dirname(self.excel_file), "Excel export directory", create_if_missing=True), None),
        ]
        if self._logging_backend_uses_google():
            results.append(
                (
                    check_required_file(
                        GOOGLE_CREDENTIALS_FILE,
                        "Google credentials",
                        guidance="Restore the service-account JSON before starting the logger.",
                    ),
                    "google_sheets",
                )
            )
        results.extend([
            (
                check_optional_json_file(
                    USER_PREFS_PATH,
                    "User preferences",
                    missing_detail="User preferences file not created yet; defaults are active and the file will be created on first save.",
                ),
                None,
            ),
            (self._check_sqlite_startup_readiness(), "local_store"),
            (self._check_google_workbook_startup(), "google_sheets"),
            (self._check_server_csv_startup(), "server_csv"),
            (self._check_printer_startup_target(), "printer"),
            (self._check_teraoka_startup_readiness(), "teraoka"),
        ])

        self.startup_checks = [result for result, _ in results]
        for result, health_signal in results:
            self._emit_startup_check(result, health_signal=health_signal)

        summary = summarize_startup_checks(self.startup_checks)
        summary_text = (
            f"Startup checks OK:{summary.get(HEALTH_OK, 0)} "
            f"WARN:{summary.get(HEALTH_WARNING, 0)} "
            f"ERR:{summary.get(HEALTH_ERROR, 0)}"
        )
        self.startup_screen.update_status(summary_text)
        log_event(
            LOGGER,
            logging.INFO,
            "startup_self_checks_complete",
            ok_count=summary.get(HEALTH_OK, 0),
            warning_count=summary.get(HEALTH_WARNING, 0),
            error_count=summary.get(HEALTH_ERROR, 0),
            unknown_count=summary.get(HEALTH_UNKNOWN, 0),
        )

    def _is_ui_thread(self):
        return threading.get_ident() == getattr(self, "_ui_thread_id", None)

    def _schedule_ui_dispatch_pump(self):
        if not getattr(self, "_ui_dispatch_running", False):
            return
        if getattr(self, "_ui_dispatch_after_id", None) is not None:
            return
        self._ui_dispatch_after_id = self.after(50, self._process_ui_dispatch_queue)

    def _queue_ui_task(self, callback, *args, **kwargs):
        if not getattr(self, "_ui_dispatch_running", False):
            return
        self._ui_task_queue.put((callback, args, kwargs))

    def _process_ui_dispatch_queue(self):
        self._ui_dispatch_after_id = None
        if not getattr(self, "_ui_dispatch_running", False):
            return

        while True:
            try:
                callback, args, kwargs = self._ui_task_queue.get_nowait()
            except queue.Empty:
                break

            try:
                callback(*args, **kwargs)
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "ui_dispatch_task_failed",
                        callback=getattr(callback, "__name__", str(callback)),
                    )
                )

        self._schedule_ui_dispatch_pump()

    def _set_health_timestamp(self, attr_name, value):
        if not self._is_ui_thread():
            self._queue_ui_task(self._set_health_timestamp, attr_name, value)
            return
        setattr(self, attr_name, value)
        self._refresh_health_display()

    def _schedule_next_production_check(self, delay_ms=60000):
        if getattr(self, "_shutdown_requested", False):
            return
        existing_after_id = getattr(self, "_production_schedule_after_id", None)
        if existing_after_id is not None:
            try:
                self.after_cancel(existing_after_id)
            except Exception:
                pass
        self._production_schedule_after_id = self.after(delay_ms, self.check_production_schedule)

    def _cancel_pending_scan_callback(self):
        pending_scan_after_id = getattr(self, "_pending_scan_after_id", None)
        if pending_scan_after_id is None:
            return
        try:
            self.after_cancel(pending_scan_after_id)
        except Exception:
            pass
        finally:
            self._pending_scan_after_id = None

    def _set_barcode_entry_value(self, value):
        self._barcode_trace_suppressed = True
        try:
            self.barcode_var.set(value)
        finally:
            self._barcode_trace_suppressed = False

    def _clear_barcode_entry(self):
        self._cancel_pending_scan_callback()
        self._set_barcode_entry_value("")

    def _calculate_scan_cycle_time(self, now):
        return calculate_scan_cycle_time(self.last_scan_time, now)

    def _build_sheet_row(self, data_map, headers):
        return build_sheet_row(data_map, headers)

    def _resolve_sheet_value(self, data_map, key):
        return resolve_sheet_value(data_map, key)

    def _normalize_sheet_text(self, value):
        return normalize_sheet_text(value)

    def _format_sheet_row_ref(self, worksheet_title, row_number):
        return format_sheet_row_ref(worksheet_title, row_number)

    def _ensure_worksheet_capacity(self, ws, min_rows=1, min_cols=1):
        try:
            current_rows = int(getattr(ws, "row_count", 0) or 0)
            current_cols = int(getattr(ws, "col_count", 0) or 0)
            if current_rows < min_rows:
                ws.add_rows(int(min_rows - current_rows))
            if current_cols < min_cols:
                ws.add_cols(int(min_cols - current_cols))
        except Exception:
            LOGGER.exception(
                structured_message(
                    "google_sheet_capacity_expand_failed",
                    worksheet=getattr(ws, "title", ""),
                    min_rows=min_rows,
                    min_cols=min_cols,
                )
            )
            raise

    def _ensure_sync_event_id_column(self, ws, title, header_row, default_headers):
        headers = list(header_row or default_headers or [])
        normalized_headers = [self._normalize_sheet_text(header) for header in headers]
        if SYNC_EVENT_ID_HEADER in normalized_headers:
            return headers, normalized_headers.index(SYNC_EVENT_ID_HEADER) + 1

        sync_col_index = max(len(headers), len(default_headers)) + 1
        self._ensure_worksheet_capacity(ws, min_rows=1, min_cols=sync_col_index)
        ws.update_cell(1, sync_col_index, SYNC_EVENT_ID_HEADER)
        while len(headers) < sync_col_index - 1:
            headers.append("")
        headers.append(SYNC_EVENT_ID_HEADER)
        log_event(
            LOGGER,
            logging.INFO,
            "google_sync_event_id_header_added",
            worksheet=title,
            column=sync_col_index,
        )
        return headers, sync_col_index

    def _sheet_row_matches_payload(self, row_values, header_row, data_map):
        return sheet_row_matches_payload(row_values, header_row, data_map, SYNC_EVENT_ID_HEADER)

    def _locate_existing_sheet_event(self, ws, title, values, header_row, event_id, data_map, sync_col_index):
        try:
            cell = ws.find(str(event_id), in_column=sync_col_index)
            if cell is not None:
                row_ref = self._format_sheet_row_ref(title, cell.row)
                log_event(
                    LOGGER,
                    logging.INFO,
                    "google_sync_event_already_present",
                    worksheet=title,
                    event_id=event_id,
                    row_ref=row_ref,
                )
                return row_ref, True
        except gspread.exceptions.CellNotFound:
            pass
        except Exception:
            LOGGER.exception(
                structured_message(
                    "google_sync_event_lookup_failed",
                    worksheet=title,
                    event_id=event_id,
                )
            )
            raise

        for row_number, row_values in enumerate(values[1:], start=2):
            existing_event_id = self._normalize_sheet_text(
                row_values[sync_col_index - 1] if len(row_values) >= sync_col_index else ""
            )
            if existing_event_id and existing_event_id != str(event_id):
                continue
            if not self._sheet_row_matches_payload(row_values, header_row, data_map):
                continue
            if not existing_event_id:
                self._ensure_worksheet_capacity(ws, min_rows=row_number, min_cols=sync_col_index)
                ws.update_cell(row_number, sync_col_index, str(event_id))
                log_event(
                    LOGGER,
                    logging.INFO,
                    "google_sync_event_reconciled",
                    worksheet=title,
                    event_id=event_id,
                    row_ref=self._format_sheet_row_ref(title, row_number),
                )
            return self._format_sheet_row_ref(title, row_number), True
        return None, False

    def _normalize_scan_dataframe(self, df):
        if df is None:
            return pd.DataFrame(columns=SCAN_HEADERS)

        if df.empty:
            return pd.DataFrame(columns=SCAN_HEADERS)

        records = normalize_scan_records(df.to_dict(orient='records'))
        normalized_df = pd.DataFrame(records)
        for header in SCAN_HEADERS:
            if header not in normalized_df.columns:
                normalized_df[header] = ""
        return normalized_df[SCAN_HEADERS]

    def _describe_google_persistence_outcome(self, scans_ok, sheet1_ok):
        successes = []
        failures = []
        for name, ok in (("Scans", scans_ok), ("Sheet1", sheet1_ok)):
            if ok:
                successes.append(name)
            else:
                failures.append(name)

        if successes and not failures:
            return "Scans and Sheet1 synced"
        if successes:
            return f"Partial sync: {', '.join(successes)}; failed {', '.join(failures)}"
        return "Scans and Sheet1 failed"

    def _update_google_sync_backlog_health(self, success_detail="All Google events synced"):
        if self.local_store is None:
            return None
        try:
            summary = self.local_store.get_google_sync_summary()
        except Exception:
            LOGGER.exception(structured_message("google_sync_summary_failed", db_path=self.local_db_file))
            self._set_health_signal("local_store", HEALTH_WARNING, "Sync summary failed")
            return None

        failed_total = int(summary.get("failed_total", 0) or 0)
        pending_total = int(summary.get("pending_total", 0) or 0)
        current_state = self.health_signals.get("google_write", {}).get("state", HEALTH_UNKNOWN)

        if failed_total > 0:
            LOGGER.warning(
                structured_message(
                    "google_sync_backlog_present",
                    **summary,
                )
            )
            if current_state != HEALTH_ERROR:
                self._set_health_signal("google_write", HEALTH_WARNING, f"Retry pending {pending_total}")
        elif pending_total > 0:
            LOGGER.warning(
                structured_message(
                    "google_sync_pending",
                    **summary,
                )
            )
            if current_state != HEALTH_ERROR:
                self._set_health_signal("google_write", HEALTH_WARNING, f"Pending sync {pending_total}")
        else:
            log_event(
                LOGGER,
                logging.INFO,
                "google_sync_backlog_cleared",
                **summary,
            )
            if current_state != HEALTH_ERROR:
                self._set_health_signal("google_write", HEALTH_OK, success_detail)
        return summary

    def _set_scan_write_health(self, detail, local_ok=False):
        if not self._is_ui_thread():
            self._queue_ui_task(
                self._set_scan_write_health,
                detail,
                local_ok=local_ok,
            )
            return None
        if local_ok:
            self.last_successful_scan_write_at = datetime.now()
            return self._set_health_signal("scan_write", HEALTH_OK, detail)
        return self._set_health_signal("scan_write", HEALTH_ERROR, detail)

    def _selected_zpl_preset_name(self):
        try:
            zpl_preset = self.__dict__.get('zpl_preset')
            if zpl_preset is not None:
                return str(zpl_preset.get() or "").strip()
        except Exception:
            pass
        return str(self.__dict__.get('_saved_zpl_preset', '') or '').strip()

    def _record_print_audit(
        self,
        *,
        job_type,
        barcode="",
        status="",
        quantity=0,
        printer_name="",
        preset_name="",
        product_code="",
        workcenter="",
        outcome="",
        error="",
    ):
        record = build_print_audit_record(
            job_type=job_type,
            barcode=barcode,
            status=status,
            quantity=quantity,
            printer_name=printer_name,
            preset_name=preset_name,
            product_code=product_code,
            workcenter=workcenter,
            outcome=outcome,
            error=error,
        )
        try:
            audit_path = getattr(self, "print_audit_file", "") or os.path.join(BASE_PATH, "data", "print_audit.csv")
            lock = getattr(self, "_print_audit_lock", None) or threading.Lock()
            append_print_audit_record(audit_path, PRINT_AUDIT_HEADERS, record, lock)
        except Exception:
            LOGGER.exception(structured_message("print_audit_write_failed", audit_file=getattr(self, "print_audit_file", "")))

        self.last_print_record = record
        if print_audit_outcome_is_success(outcome):
            log_event(LOGGER, logging.INFO, "print_audit_recorded", **record)
            self._set_health_signal("print", HEALTH_OK, f"{job_type} queued")
        else:
            LOGGER.error(structured_message("print_audit_recorded", **record))
            self._set_health_signal("print", HEALTH_ERROR, f"{job_type} failed")
        return record

    def _read_recent_print_audit(self, limit=20):
        audit_path = getattr(self, "print_audit_file", "") or os.path.join(BASE_PATH, "data", "print_audit.csv")
        try:
            return read_recent_print_audit(audit_path, limit)
        except Exception:
            LOGGER.exception(structured_message("print_audit_read_failed", audit_file=audit_path))
            return []

    def _tail_text_file(self, path, line_limit=80):
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()[-int(line_limit):]
        except Exception:
            LOGGER.exception(structured_message("log_tail_read_failed", path=path))
            return []

    def _format_print_audit_rows(self, rows):
        return format_print_audit_rows(rows)

    def _format_health_details(self):
        try:
            workcenter = self.current_workcenter
            include_workcenter = True
        except Exception:
            workcenter = ""
            include_workcenter = False
        return build_health_details_text(
            self.VERSION,
            workcenter,
            include_workcenter,
            self.health_signals,
            self.local_store,
            self.last_print_record,
            PRINT_AUDIT_HEADERS,
        )

    def _format_live_status_details(self):
        def _read_var(text_var, default="-"):
            try:
                value = str(text_var.get() or "").strip()
                return value or default
            except Exception:
                return default

        lines = [
            "Dashboard Status",
            f"Production: {_read_var(self.production_state_var)}",
            f"Workcenter: {getattr(self, 'current_workcenter', '-')}",
            f"Logging backend: {getattr(self, 'logging_backend', LOG_BACKEND_GOOGLE)}",
            f"Server CSV root: {getattr(self, 'server_csv_dir', '') or '-'}",
            f"Product: {_read_var(self.product_var)}",
            f"Description: {_read_var(self.description_var)}",
            f"Last Scanned: {_read_var(self.last_scanned_var)}",
            f"Current Cycle: {_read_var(self.cycle_time_var)}",
            f"Expected Cycle: {_read_var(self.expected_cycle_var)}",
            f"Auto Downtime Trigger: {self._format_auto_downtime_multiplier(self._get_auto_downtime_multiplier())} x expected cycle",
            "",
            "Printer",
            _read_var(self.printer_status_var, "Printer Status: -"),
            "",
            "Teraoka",
            _read_var(self.teraoka_status_var, "Teraoka: -"),
            f"Job: {_read_var(self.teraoka_job_var)}",
            f"Planned Product: {_read_var(self.teraoka_product_var)}",
            _read_var(self.teraoka_quantity_var, "Outstanding: -"),
            _read_var(self.teraoka_required_quantity_var, "Required Qty: -"),
            _read_var(self.teraoka_qty_made_var, "Qty Made: -"),
            "",
            "Health / Writes",
            _read_var(self.integration_health_var, "Health: -"),
            _read_var(self.write_health_var, "Writes: -"),
        ]
        return "\n".join(lines)

    def _redact_diagnostics_data(self, value, key_name=""):
        return redact_diagnostics_data(value, key_name)

    def _read_redacted_json_file(self, path):
        return read_redacted_json_file(path)

    def _diagnostics_metadata(self):
        return build_diagnostics_metadata(
            app_version=self.VERSION,
            app_run_id=APP_RUN_ID,
            log_context=get_log_context(),
            host=APP_HOSTNAME,
            base_path=BASE_PATH,
            workcenter=getattr(self, "current_workcenter", ""),
            logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
            server_csv_dir=getattr(self, "server_csv_dir", ""),
            server_csv_station_dir=self._server_csv_station_dir(),
            selected_zpl_preset=self._selected_zpl_preset_name(),
            label_width_mm=LABEL_WIDTH,
            label_height_mm=LABEL_HEIGHT,
            print_quantity=getattr(self, "print_quantity", ""),
            auto_downtime_multiplier=getattr(self, "auto_downtime_multiplier", ""),
            health_signals=getattr(self, "health_signals", {}),
            google_credentials_file=GOOGLE_CREDENTIALS_FILE,
            excel_file=getattr(self, "excel_file", ""),
            local_db_file=getattr(self, "local_db_file", ""),
            print_audit_file=getattr(self, "print_audit_file", ""),
        )

    def export_diagnostics_bundle(self):
        started_at = time.perf_counter()
        bundle_id = make_correlation_id("diag")
        diagnostics_dir = os.path.join(BASE_PATH, "diagnostics")
        os.makedirs(diagnostics_dir, exist_ok=True)
        filename = f"FMS_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{bundle_id}.zip"
        bundle_path = os.path.join(diagnostics_dir, filename)
        included = []

        def add_existing_file(zip_file, path, archive_name):
            if path and os.path.exists(path):
                zip_file.write(path, archive_name)
                included.append(archive_name)

        try:
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr(
                    "metadata.json",
                    json.dumps(self._diagnostics_metadata(), ensure_ascii=False, default=str, indent=2),
                )
                zip_file.writestr("live_status.txt", self._format_live_status_details())
                zip_file.writestr("health.txt", self._format_health_details())
                included.extend(["metadata.json", "live_status.txt", "health.txt"])

                logs_dir = os.path.join(BASE_PATH, "logs")
                for log_name in ("production.log", "production_errors.log", "dashboard.log", "dashboard_errors.log"):
                    add_existing_file(zip_file, os.path.join(logs_dir, log_name), f"logs/{log_name}")

                add_existing_file(
                    zip_file,
                    getattr(self, "print_audit_file", os.path.join(BASE_PATH, "data", "print_audit.csv")),
                    "data/print_audit.csv",
                )
                for sheet_name, filename in SERVER_CSV_FILENAMES.items():
                    add_existing_file(zip_file, self._server_csv_path(sheet_name), f"server_csv/{filename}")

                for config_path in (
                    USER_PREFS_PATH,
                    PRODUCTION_SCHEDULE_FILE,
                    TERAOKA_CONFIG_PATH,
                    os.path.join(BASE_PATH, "config.json"),
                ):
                    if config_path and os.path.exists(config_path):
                        redacted = self._read_redacted_json_file(config_path)
                        archive_name = f"config/{os.path.basename(config_path)}.redacted.json"
                        zip_file.writestr(archive_name, json.dumps(redacted, ensure_ascii=False, default=str, indent=2))
                        included.append(archive_name)

            log_timing(
                LOGGER,
                logging.INFO,
                "diagnostics_bundle_created",
                started_at,
                diagnostics_bundle_id=bundle_id,
                path=bundle_path,
                included_files=len(included),
            )
            messagebox.showinfo("Diagnostics Bundle", f"Diagnostics bundle created:\n{bundle_path}", parent=self)
            return bundle_path
        except Exception as e:
            LOGGER.exception(
                structured_message(
                    "diagnostics_bundle_failed",
                    diagnostics_bundle_id=bundle_id,
                    path=bundle_path,
                    duration_ms=elapsed_ms(started_at),
                )
            )
            messagebox.showerror("Diagnostics Bundle", f"Could not create diagnostics bundle:\n{e}", parent=self)
            return ""

    def _show_text_in_box(self, textbox, value):
        set_textbox_value(textbox, value)

    def _reprint_last_label(self):
        context = getattr(self, "last_label_context", None)
        if not context:
            messagebox.showwarning("No Label", "No successful label is available to reprint yet.")
            return False
        if not messagebox.askyesno("Reprint Last Label", f"Reprint label for {context.get('barcode_text', '')}?"):
            return False
        return self.print_label(
            barcode_text=context.get("barcode_text", ""),
            description=context.get("description", "N/A"),
            Barc=context.get("Barc", "N/A"),
            PC=context.get("PC", "N/A"),
            status="Reprint",
            job_type="Reprint",
            update_last_context=False,
            scan_id=context.get("scan_id", ""),
        )

    def show_status_logs_dialog(self):
        def errors_text():
            errors_path = os.path.join(BASE_PATH, "logs", "production_errors.log")
            errors = "".join(self._tail_text_file(errors_path, line_limit=120)).strip()
            return errors or "No recent error log entries."

        return create_status_logs_dialog(
            self,
            live_status_text=self._format_live_status_details,
            health_details_text=self._format_health_details,
            print_audit_text=lambda: self._format_print_audit_rows(self._read_recent_print_audit(limit=50)),
            errors_text=errors_text,
            sync_now=self.sync_all_to_google_sheets,
            reprint_last_label=self._reprint_last_label,
            export_diagnostics_bundle=self.export_diagnostics_bundle,
            present_dialog=self._present_app_dialog,
        )

    def poll_teraoka_status(self):
        started_at = time.perf_counter()
        outcome = "unknown"
        try:
            if not self.teraoka_enabled.get():
                self.teraoka_status_var.set("Teraoka: DISABLED")
                self.teraoka_job_var.set("-")
                self.teraoka_product_var.set("-")
                self.teraoka_quantity_var.set("Outstanding: -")
                self.teraoka_required_quantity_var.set("Required Qty: -")
                self.teraoka_qty_made_var.set("Qty Made: -")
                try:
                    self.teraoka_status_label.configure(text_color="orange")
                except Exception:
                    pass
                self._set_health_signal("teraoka", HEALTH_UNKNOWN, "Disabled")
                outcome = "disabled"
            else:
                status = read_teraoka_status(getattr(self, 'teraoka', None))
                connected = status["connected"]
                job = status["job"]
                product_code = status["product_code"]
                required_quantity = status["required_quantity"]
                total_quantity = status["total_quantity"]
                qty_made = status["qty_made"]
                last_err = status["last_error"]
                
                if connected:
                    self.teraoka_status_var.set("Teraoka: CONNECTED")
                    if job:
                        self.teraoka_job_var.set(f"{job}")
                        # Update product and quantity labels if available
                        if product_code is not None:
                            self.teraoka_product_var.set(f"{product_code}")
                        if required_quantity is not None:
                            self.teraoka_quantity_var.set(f"Outstanding: {required_quantity}")
                        if total_quantity is not None:
                            self.teraoka_required_quantity_var.set(f"Required Qty: {total_quantity}")
                        if qty_made is not None:
                            self.teraoka_qty_made_var.set(f"Qty Made: {qty_made}")
                    else:
                        self.teraoka_job_var.set("-")
                        self.teraoka_product_var.set("-")
                        self.teraoka_quantity_var.set("Outstanding: -")
                        self.teraoka_required_quantity_var.set("Required Qty: -")
                        self.teraoka_qty_made_var.set("Qty Made: -")
                    try:
                        self.teraoka_status_label.configure(text_color="green")
                    except Exception:
                        pass
                    teraoka_detail = "Connected" if job else "Connected; waiting for job"
                    teraoka_state = HEALTH_OK if job else HEALTH_WARNING
                    self._set_health_signal("teraoka", teraoka_state, teraoka_detail)
                    outcome = "connected_with_job" if job else "connected_waiting_for_job"
                else:
                    if last_err:
                        self.teraoka_status_var.set(f"Teraoka: DISCONNECTED ({last_err})")
                    else:
                        self.teraoka_status_var.set("Teraoka: DISCONNECTED")
                    self.teraoka_job_var.set("-")
                    self.teraoka_product_var.set("-")
                    self.teraoka_quantity_var.set("Outstanding: -")
                    self.teraoka_required_quantity_var.set("Required Qty: -")
                    self.teraoka_qty_made_var.set("Qty Made: -")
                    try:
                        self.teraoka_status_label.configure(text_color="red")
                    except Exception:
                        pass
                    self._set_health_signal("teraoka", HEALTH_WARNING, last_err or "Disconnected")
                    outcome = "disconnected"
        except Exception:
            outcome = "failed"
            LOGGER.exception(structured_message("teraoka_status_poll_failed"))
            self._set_health_signal("teraoka", HEALTH_ERROR, "Status poll failed")
        finally:
            try:
                status_text = self.teraoka_status_var.get()
            except Exception:
                status_text = ""
            log_timing(
                LOGGER,
                logging.DEBUG,
                "teraoka_status_poll_timing",
                started_at,
                min_duration_ms=500,
                outcome=outcome,
                status_text=status_text,
            )
            try:
                self._apply_status_colors()
            except Exception:
                pass
            try:
                self._update_scan_entry_state()
            except Exception:
                pass
            self.after(2000, self.poll_teraoka_status)

    def _load_teraoka_config(self):
        try:
            config = load_teraoka_config_file(TERAOKA_CONFIG_PATH)
            if config.get("loaded"):
                if config.get("workcenters"):
                    self.workcenters = config["workcenters"]
                if config.get("wsdl_url"):
                    self.teraoka_wsdl = config["wsdl_url"]
                if config.get("default_supervisor"):
                    self.teraoka_supervisor = config["default_supervisor"]
                if config.get("admin_password"):
                    self.teraoka_admin_pw = config["admin_password"]
                log_event(
                    LOGGER,
                    logging.INFO,
                    "teraoka_config_loaded",
                    path=TERAOKA_CONFIG_PATH,
                    workcenter_count=len(self.workcenters),
                    wsdl=self.teraoka_wsdl,
                )
        except Exception:
            LOGGER.exception(
                structured_message(
                    "teraoka_config_load_failed",
                    path=TERAOKA_CONFIG_PATH,
                )
            )
            self._set_health_signal("teraoka", HEALTH_WARNING, "Config load failed")

    def _get_production_schedule_mtime(self):
        return get_production_schedule_mtime(PRODUCTION_SCHEDULE_FILE)

    def _refresh_production_schedule_config_if_needed(self):
        current_mtime = self._get_production_schedule_mtime()
        if (
            getattr(self, "_production_schedule_config", None) is None
            or getattr(self, "_production_schedule_mtime", None) != current_mtime
        ):
            self._production_schedule_config = _load_production_schedule_config()
            self._production_schedule_mtime = current_mtime

    def _get_active_planned_break_window(self, now=None):
        self._refresh_production_schedule_config_if_needed()
        return active_planned_break_window(
            self._production_schedule_config,
            self.current_workcenter,
            PLANNED_BREAK_DEFINITIONS,
            now,
        )

    def _start_downtime_sync_worker(self, event_id, context_label):
        try:
            threading.Thread(
                target=self._async_sync_downtime_event,
                args=(event_id,),
                daemon=True,
            ).start()
        except Exception:
            LOGGER.exception(
                structured_message(
                    "downtime_sync_worker_failed",
                    context=context_label,
                    event_id=event_id,
                    workcenter=self.current_workcenter,
                )
            )
            self._set_health_signal("excel", HEALTH_WARNING, f"{context_label} stored locally; export worker failed")
            self._set_health_signal("google_write", HEALTH_WARNING, f"{context_label} stored locally; sync worker failed")

    def _ensure_planned_break_event_logged(self, break_window):
        downtime_row = build_downtime_event_row(
            timestamp=break_window["start"],
            duration_seconds=(break_window["end"] - break_window["start"]).total_seconds(),
            reason=break_window["label"],
            description="Scheduled break",
            operator="",
            workcenter=break_window["workcenter"],
        )
        try:
            event_id, inserted = self._require_local_store().append_downtime_event(downtime_row)
        except Exception:
            LOGGER.exception(
                structured_message(
                    "planned_break_local_commit_failed",
                    reason=break_window["label"],
                    workcenter=break_window["workcenter"],
                    start_at=format_contract_timestamp(break_window["start"]),
                    end_at=format_contract_timestamp(break_window["end"]),
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_ERROR, "Planned break commit failed")
            return False

        if inserted:
            self._set_local_store_health_success("Planned break committed locally")
            log_event(
                LOGGER,
                logging.INFO,
                "planned_break_logged",
                reason=break_window["label"],
                workcenter=break_window["workcenter"],
                start_at=format_contract_timestamp(break_window["start"]),
                end_at=format_contract_timestamp(break_window["end"]),
                duration_seconds=f"{(break_window['end'] - break_window['start']).total_seconds():.2f}",
                event_id=event_id,
            )
        else:
            log_event(
                LOGGER,
                logging.INFO,
                "planned_break_already_logged",
                reason=break_window["label"],
                workcenter=break_window["workcenter"],
                start_at=format_contract_timestamp(break_window["start"]),
                event_id=event_id,
            )

        self._start_downtime_sync_worker(event_id, "Planned break")
        return True

    def _finalize_planned_break_context(self, now):
        context = getattr(self, "_active_planned_break_context", None)
        if not context or now < context["end"]:
            return

        saw_scan_during_break = bool(context.get("saw_scan_during_break"))
        if saw_scan_during_break:
            log_event(
                LOGGER,
                logging.INFO,
                "planned_break_skipped_due_to_activity",
                reason=context["label"],
                workcenter=context["workcenter"],
                start_at=format_contract_timestamp(context["start"]),
                end_at=format_contract_timestamp(context["end"]),
            )
        else:
            self._ensure_planned_break_event_logged(context)

        if not isinstance(self.last_scan_time, datetime) or self.last_scan_time < context["end"]:
            # Keep planned breaks from immediately re-triggering auto downtime and
            # from inflating the next cycle time measurement with scheduled-stop time.
            self.last_scan_time = context["end"]

        self._active_planned_break_context = None

    def _normalize_current_workcenter(self):
        workcenters, selected_workcenter, previous_workcenter, changed, available_count = normalize_workcenter_selection(
            self.workcenters,
            getattr(self, "current_workcenter", ""),
            TERAOKA_WORKCENTER,
        )
        self.workcenters = workcenters
        if changed:
            self.current_workcenter = selected_workcenter
            log_event(
                LOGGER,
                logging.INFO,
                "workcenter_selection_normalized",
                previous=previous_workcenter,
                selected=self.current_workcenter,
                available=available_count,
            )

    def _on_workcenter_selected(self, new_wc_id: str):
        # Store the current workcenter in case we need to revert
        old_wc_id = self.current_workcenter
            
        # Prompt for password before applying change
        def do_cancel():
            dlg.destroy()

        def do_ok():
            pw = pw_var.get()
            if (pw or "") != (self.teraoka_admin_pw or "admin"):
                messagebox.showerror("Access Denied", "Incorrect password.")
                dlg.destroy()
                return
            dlg.destroy()
            # Only update the workcenter if password is correct
            self._switch_workcenter(new_wc_id)

        dlg = ctk.CTkToplevel(self)
        dlg.title("Change Workcenter")
        dlg.geometry("350x160")
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=f"Change workcenter to: {new_wc_id}", font=("Arial", 14, "bold")).pack(pady=(15, 10))
        pw_var = ctk.StringVar()
        pw_entry = ctk.CTkEntry(dlg, textvariable=pw_var, placeholder_text="Admin password", show="*")
        pw_entry.pack(padx=20, pady=10, fill="x")
        self.enable_touch_keyboard(pw_entry)  # Enable touch keyboard for password entry
        btns = ctk.CTkFrame(dlg)
        btns.pack(pady=10)
        ctk.CTkButton(btns, text="Cancel", command=do_cancel, width=100).pack(side="left", padx=10)
        ctk.CTkButton(btns, text="OK", command=do_ok, width=100).pack(side="right", padx=10)
        dlg.lift(); dlg.focus_force()
        pw_entry.focus_set()

    def _switch_workcenter(self, new_wc_id: str):
        try:
            if hasattr(self, 'teraoka') and self.teraoka:
                self.teraoka.shutdown()
        except Exception:
            LOGGER.exception(structured_message("teraoka_shutdown_failed_during_workcenter_switch", workcenter=new_wc_id))
            
        # Update the workcenter
        self.current_workcenter = new_wc_id
        self._update_log_context()
        
        # Update the UI elements
        if hasattr(self, 'workcenter_var'):
            self.workcenter_var.set(new_wc_id)
            
        # Update the workcenter display label if it exists
        if hasattr(self, 'workcenter_display'):
            self.workcenter_display.configure(text=new_wc_id)
            # Force update the display
            self.workcenter_display.update_idletasks()
            
        try:
            self._save_user_prefs()
        except Exception as e:
            print(f"Error saving user prefs: {e}")
            
        # Update Teraoka connection if enabled
        if self.teraoka_enabled.get():
            self.teraoka_status_var.set("Teraoka: CONNECTING...")
            self._set_health_signal("teraoka", HEALTH_WARNING, f"Connecting to {new_wc_id}")
            try:
                teraoka_client_class = load_teraoka_client()
                self.teraoka = teraoka_client_class(self.teraoka_wsdl, self.current_workcenter, self.teraoka_supervisor)
                self.teraoka.start()
                try:
                    self.teraoka.enqueue_receipt(0)
                except Exception as e:
                    print(f"Error enqueuing receipt: {e}")
                    LOGGER.exception(structured_message("teraoka_enqueue_failed_on_workcenter_switch", workcenter=new_wc_id))
            except Exception as e:
                print(f"Error starting Teraoka client: {e}")
                LOGGER.exception(structured_message("teraoka_start_failed_on_workcenter_switch", workcenter=new_wc_id))
                self._set_health_signal("teraoka", HEALTH_ERROR, f"Start failed for {new_wc_id}")
        else:
            self.teraoka = None
            self.teraoka_status_var.set("Teraoka: DISABLED")
            self.teraoka_job_var.set("Job: -")
            self._set_health_signal("teraoka", HEALTH_UNKNOWN, "Disabled")

    def _load_user_prefs(self):
        try:
            prefs = getattr(self, "_startup_prefs", None)
            if prefs is None:
                prefs = _load_user_prefs_file()
            if prefs:
                    if 'last_workcenter' in prefs:
                        self.current_workcenter = prefs['last_workcenter']
                    if 'last_zpl_preset' in prefs:
                        self._saved_zpl_preset = prefs['last_zpl_preset']
                    if 'logging_backend' in prefs:
                        self._set_logging_backend(prefs['logging_backend'])
                    if 'server_csv_dir' in prefs:
                        self.server_csv_dir = str(prefs.get('server_csv_dir') or '').strip()
                    if 'teraoka_enabled' in prefs:
                        self.teraoka_enabled.set(prefs['teraoka_enabled'])
                    if 'print_quantity' in prefs:
                        self.print_quantity = prefs['print_quantity']
                    if 'custom_zpl_presets_dir' in prefs and prefs['custom_zpl_presets_dir']:
                        self.custom_zpl_presets_dir = prefs['custom_zpl_presets_dir']
                    if 'auto_prod_enabled' in prefs:
                        self.auto_prod_enabled.set(prefs['auto_prod_enabled'])
                    if 'overtime_enabled' in prefs:
                        self.overtime_enabled.set(prefs['overtime_enabled'])
                    if 'auto_start_time' in prefs:
                        self.auto_start_time.set(prefs['auto_start_time'])
                    if 'auto_stop_time' in prefs:
                        self.auto_stop_time.set(prefs['auto_stop_time'])
                    if 'overtime_start_time' in prefs:
                        self.overtime_start_time.set(prefs['overtime_start_time'])
                    if 'overtime_stop_time' in prefs:
                        self.overtime_stop_time.set(prefs['overtime_stop_time'])
                    if 'auto_downtime_multiplier' in prefs:
                        try:
                            self._set_auto_downtime_multiplier(prefs['auto_downtime_multiplier'])
                        except Exception:
                            self._set_auto_downtime_multiplier(2.5)
                    width_pref = prefs.get('label_width_mm')
                    height_pref = prefs.get('label_height_mm')
                    if width_pref is not None and height_pref is not None:
                        self._set_label_dimensions(width_pref, height_pref)
        except Exception as e:
            print(f"Error loading user prefs: {e}")
            self.print_quantity = 2  # Default value on error

    def _save_user_prefs(self):
        try:
            prefs = {
                'last_workcenter': getattr(self, 'current_workcenter', ''),
                'last_zpl_preset': '',
                'teraoka_enabled': self.teraoka_enabled.get(),
                'print_quantity': getattr(self, 'print_quantity', 2),
                'custom_zpl_presets_dir': getattr(self, 'custom_zpl_presets_dir', ''),
                'auto_prod_enabled': self.auto_prod_enabled.get(),
                'overtime_enabled': self.overtime_enabled.get(),
                'auto_start_time': self.auto_start_time.get(),
                'auto_stop_time': self.auto_stop_time.get(),
                'overtime_start_time': self.overtime_start_time.get(),
                'overtime_stop_time': self.overtime_stop_time.get(),
                'auto_downtime_multiplier': getattr(self, 'auto_downtime_multiplier', 2.5),
                'label_width_mm': LABEL_WIDTH,
                'label_height_mm': LABEL_HEIGHT,
                'logging_backend': getattr(self, 'logging_backend', LOG_BACKEND_GOOGLE),
                'server_csv_dir': getattr(self, 'server_csv_dir', ''),
            }
            try:
                if hasattr(self, 'zpl_preset') and self.zpl_preset is not None:
                    prefs['last_zpl_preset'] = str(self.zpl_preset.get() or '')
            except Exception:
                pass
            # Ensure directory exists
            os.makedirs(os.path.dirname(USER_PREFS_PATH), exist_ok=True)
            with open(USER_PREFS_PATH, 'w', encoding='utf-8') as f:
                json.dump(prefs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving user prefs: {e}")

    def _on_zpl_preset_changed(self, value=None):
        try:
            selected_preset = str(
                value if value is not None else (self.zpl_preset.get() if hasattr(self, 'zpl_preset') else '')
            ).strip()
            self._apply_selected_zpl_preset_dimensions(selected_preset)
            # Save the selected preset to user preferences
            self._save_user_prefs()
            
            # If we're in the setup popup and a ZPL text widget exists, load the template
            if hasattr(self, 'setup_zpl_text_widget') and self.setup_zpl_text_widget.winfo_exists():
                zpl_content = self.get_zpl_template()
                if zpl_content is not None:
                    self.setup_zpl_text_widget.configure(state="normal")
                    self.setup_zpl_text_widget.delete("1.0", "end")
                    self.setup_zpl_text_widget.insert("1.0", zpl_content)
                    self.setup_zpl_text_widget.see("1.0")
                    self.setup_zpl_text_widget.configure(state="normal")
        except Exception as e:
            print(f"Error in _on_zpl_preset_changed: {e}")
            import traceback
            traceback.print_exc()

    # ------------------- GOOGLE SHEETS APPEND HELPERS -------------------
    def _append_row_with_retry(self, ws, row_values, max_retries=5):
        try:
            import time
        except Exception:
            pass
        attempt = 0
        backoff = 0.5
        while True:
            try:
                ws.append_row(row_values, value_input_option='USER_ENTERED')
                return True
            except Exception as e:
                attempt += 1
                LOGGER.warning(
                    structured_message(
                        "google_sheets_append_retry",
                        worksheet=getattr(ws, 'title', 'unknown'),
                        attempt=attempt,
                        max_retries=max_retries,
                        error=str(e),
                    )
                )
                if attempt >= max_retries:
                    print(f"Append failed after {attempt} attempts: {e}")
                    LOGGER.exception(
                        structured_message(
                            "google_sheets_append_failed",
                            worksheet=getattr(ws, 'title', 'unknown'),
                            attempts=attempt,
                        )
                    )
                    return False
                try:
                    time.sleep(backoff)
                except Exception:
                    pass
                backoff = min(backoff * 2, 8)

    def _get_or_create_sheet_with_headers(self, title, default_headers):
        try:
            try:
                ws = sheet.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                ws = sheet.add_worksheet(title=title, rows=1000, cols=max(20, len(default_headers)))
            # Ensure headers exist; if first cell empty, write headers
            try:
                values = ws.get_all_values()
                if not values or not values[0] or all(not c for c in values[0]):
                    ws.append_row(default_headers)
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "google_sheets_header_check_failed",
                        worksheet=title,
                    )
                )
                self._set_health_signal("google_sheets", HEALTH_WARNING, f"Header check failed for {title}")
            return ws
        except Exception as e:
            print(f"Error getting/creating sheet '{title}': {e}")
            LOGGER.exception(
                structured_message(
                    "google_sheets_get_or_create_failed",
                    worksheet=title,
                )
            )
            self._set_health_signal("google_sheets", HEALTH_ERROR, f"Sheet access failed: {title}")
            raise

    def _append_map_to_sheet(self, title, data_map, default_headers, event_id=None):
        ws = self._get_or_create_sheet_with_headers(title, default_headers)
        # Read the raw first row from the sheet (preserves leading empty cells)
        values = []
        try:
            values = ws.get_all_values()
            header_row = values[0] if values and values[0] else default_headers
        except Exception:
            LOGGER.exception(
                structured_message(
                    "google_sheets_header_read_failed",
                    worksheet=title,
                )
            )
            self._set_health_signal("google_sheets", HEALTH_WARNING, f"Header read fallback: {title}")
            header_row = default_headers

        if event_id:
            header_row, sync_col_index = self._ensure_sync_event_id_column(ws, title, header_row, default_headers)
            if values:
                values[0] = header_row
            else:
                values = [header_row]

            existing_row_ref, existing = self._locate_existing_sheet_event(
                ws,
                title,
                values,
                header_row,
                event_id,
                data_map,
                sync_col_index,
            )
            if existing:
                self._set_health_timestamp("last_successful_google_write_at", datetime.now())
                self._set_health_signal("google_sheets", HEALTH_OK, "Connected")
                self._set_health_signal("google_write", HEALTH_OK, f"Verified {title}")
                return {"ok": True, "existing": True, "row_ref": existing_row_ref}
        else:
            sync_col_index = None

        effective_headers = list(header_row)
        if len(effective_headers) < len(default_headers):
            effective_headers.extend(default_headers[len(effective_headers):])
        if event_id:
            while len(effective_headers) < sync_col_index - 1:
                effective_headers.append("")
            if len(effective_headers) == sync_col_index - 1:
                effective_headers.append(SYNC_EVENT_ID_HEADER)
            else:
                effective_headers[sync_col_index - 1] = SYNC_EVENT_ID_HEADER

        row = self._build_sheet_row(data_map, effective_headers)
        if event_id and sync_col_index:
            while len(row) < sync_col_index:
                row.append("")
            row[sync_col_index - 1] = str(event_id)

        ok = self._append_row_with_retry(ws, row)
        if ok:
            self._set_health_timestamp("last_successful_google_write_at", datetime.now())
            self._set_health_signal("google_sheets", HEALTH_OK, "Connected")
            self._set_health_signal("google_write", HEALTH_OK, f"Last write {title}")
            row_ref = None
            if event_id and sync_col_index:
                try:
                    cell = ws.find(str(event_id), in_column=sync_col_index)
                    row_ref = self._format_sheet_row_ref(title, cell.row) if cell is not None else None
                except gspread.exceptions.CellNotFound:
                    row_ref = None
                except Exception:
                    LOGGER.exception(
                        structured_message(
                            "google_sync_event_row_ref_lookup_failed",
                            worksheet=title,
                            event_id=event_id,
                        )
                    )
        else:
            self._set_health_signal("google_sheets", HEALTH_ERROR, f"Append failed: {title}")
            self._set_health_signal("google_write", HEALTH_ERROR, f"Write failed: {title}")
            row_ref = None
        return {"ok": ok, "existing": False, "row_ref": row_ref}

    def initialize_local_store(self):
        started_at = time.perf_counter()
        try:
            self.local_store = create_local_event_store(self.local_db_file, LocalEventStore)
            self._set_local_store_health_success("SQLite ready")
            log_event(
                LOGGER,
                logging.INFO,
                "local_store_initialized",
                path=self.local_db_file,
                duration_ms=elapsed_ms(started_at),
            )
        except Exception as e:
            self.local_store = None
            LOGGER.exception(
                structured_message(
                    "local_store_initialization_failed",
                    db_path=self.local_db_file,
                    duration_ms=elapsed_ms(started_at),
                )
            )
            self._set_health_signal("local_store", HEALTH_ERROR, "SQLite init failed")
            self._set_health_signal("scan_write", HEALTH_ERROR, "Local store unavailable")
            print(f"Error initializing local event store: {e}")

    def _require_local_store(self):
        if self.local_store is None:
            raise RuntimeError("Local event store is unavailable.")
        return self.local_store

    def _bootstrap_local_store_from_excel(self):
        if self.local_store is None or not os.path.exists(self.excel_file):
            return 0
        if self.local_store.has_any_scan_events():
            return 0

        imported = 0
        try:
            df = pd.read_excel(self.excel_file, engine='openpyxl')
            normalized_df = self._normalize_scan_dataframe(df)
            for row in normalized_df.to_dict(orient='records'):
                normalized_barcode = self._normalize_barcode(row.get("Barcode", ""))
                _, inserted = self.local_store.append_scan_event(
                    row,
                    normalized_barcode=normalized_barcode,
                    bootstrap_synced=True,
                )
                if inserted:
                    imported += 1
            if imported:
                log_event(
                    LOGGER,
                    logging.INFO,
                    "local_store_bootstrap_from_excel_complete",
                    imported_rows=imported,
                    excel_file=self.excel_file,
                )
            self._set_local_store_health_success("Excel bootstrap checked")
            return imported
        except Exception:
            LOGGER.exception(
                structured_message(
                    "local_store_bootstrap_from_excel_failed",
                    excel_file=self.excel_file,
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_WARNING, "Excel bootstrap failed")
            return 0

    def _load_local_barcodes(self):
        if self.local_store is None:
            self.scanned_barcodes = set()
            return set()

        try:
            local_barcodes = self.local_store.load_known_barcodes()
            self.scanned_barcodes = set(local_barcodes)
            with self._barcode_cache_lock:
                self._barcode_cache |= local_barcodes
                self._barcode_cache_last_update = time.time()
            self._set_local_store_health_success("Barcode cache loaded")
            return local_barcodes
        except Exception:
            LOGGER.exception(
                structured_message(
                    "local_store_barcode_load_failed",
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_ERROR, "Barcode cache load failed")
            self.scanned_barcodes = set()
            return set()

    def _build_export_dataframe(self, rows, headers, normalize_scans=False):
        return build_export_dataframe(pd, rows, headers, normalize_scans, self._normalize_scan_dataframe)

    def _server_csv_root_dir(self):
        return server_csv_root_dir(getattr(self, "server_csv_dir", ""))

    def _server_csv_station_dir(self):
        root = self._server_csv_root_dir()
        return server_csv_station_dir(root, getattr(self, "current_workcenter", ""), APP_HOSTNAME)

    def _server_csv_path(self, sheet_name):
        station_dir = self._server_csv_station_dir()
        return server_csv_path(station_dir, sheet_name, SERVER_CSV_FILENAMES)

    def _server_product_csv_paths(self):
        root = self._server_csv_root_dir()
        return server_product_csv_paths(root, self._server_product_csv_path())

    def _server_product_csv_path(self):
        root = self._server_csv_root_dir()
        return server_product_csv_path(root)

    def _write_rows_to_csv_atomic(self, path, rows, headers):
        write_rows_to_csv_atomic(path, rows, headers, APP_RUN_ID)

    def _read_csv_records(self, path):
        return read_csv_records(path)

    def _google_product_rows_for_server_csv(self):
        values = []
        try:
            if product_sheet is None:
                if not self._logging_backend_uses_google() and not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                    return []
                initialize_google_sheets()
            values = product_sheet.get_all_values()
        except Exception:
            LOGGER.exception(structured_message("server_csv_product_seed_google_load_failed"))
            return []

        product_code_index = PRODUCT_LOOKUP_COLUMNS["Product Code"]
        description_index = PRODUCT_LOOKUP_COLUMNS["Description"]
        expected_cycle_index = PRODUCT_LOOKUP_COLUMNS["Expected Cycle"]
        barcode_display_index = PRODUCT_LOOKUP_COLUMNS["Barcode Display"]
        rows = []
        for source_row in values[1:]:
            code = str(source_row[product_code_index] if len(source_row) > product_code_index else "").strip()
            if not code:
                continue
            rows.append(
                {
                    "Product Code": code,
                    "Description": str(source_row[description_index] if len(source_row) > description_index else "").strip(),
                    "Expected Cycle": str(source_row[expected_cycle_index] if len(source_row) > expected_cycle_index else "").strip(),
                    "Barcode Display": str(source_row[barcode_display_index] if len(source_row) > barcode_display_index else "").strip(),
                }
            )
        return rows

    def _loaded_product_rows_for_server_csv(self):
        rows = []
        for record in getattr(self, "product_records", []) or []:
            code = str(record.get("code", "") or "").strip()
            if not code:
                continue
            rows.append(
                {
                    "Product Code": code,
                    "Description": str(record.get("description", "") or "").strip(),
                    "Expected Cycle": str(record.get("expected_cycle", "") or "").strip(),
                    "Barcode Display": str(record.get("barcode", "") or "").strip(),
                }
            )
        return rows

    def _server_product_seed_rows(self):
        rows = self._google_product_rows_for_server_csv()
        if rows:
            return rows
        return self._loaded_product_rows_for_server_csv()

    def _ensure_server_csv_file(self, path, headers):
        if path and os.path.exists(path) and os.path.getsize(path) > 0:
            return False
        self._write_rows_to_csv_atomic(path, [], headers)
        return True

    def initialize_server_csv_structure(self, show_dialog=True):
        root = self._server_csv_root_dir()
        if not root:
            message = "No server CSV directory has been configured."
            if show_dialog:
                messagebox.showwarning("Server CSV", message, parent=self)
            self._set_health_signal("server_csv", HEALTH_WARNING, message)
            return False

        created = []
        product_rows_count = 0
        try:
            station_dir = self._server_csv_station_dir()
            os.makedirs(station_dir, exist_ok=True)

            test_path = os.path.join(station_dir, f"permission_test_{APP_RUN_ID}.tmp")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(format_contract_timestamp(datetime.now()))
            os.remove(test_path)

            for sheet_name, headers in (
                (SHEET_SCANS, SCAN_HEADERS),
                (SHEET_PRODUCTION, PRODUCTION_HEADERS),
                (SHEET_DOWNTIME, DOWNTIME_HEADERS),
            ):
                path = self._server_csv_path(sheet_name)
                if self._ensure_server_csv_file(path, headers):
                    created.append(path)

            product_path = self._server_product_csv_path()
            existing_product_rows = self._read_csv_records(product_path) if os.path.exists(product_path) else []
            if not existing_product_rows:
                product_rows = self._server_product_seed_rows()
                self._write_rows_to_csv_atomic(product_path, product_rows, SERVER_PRODUCT_HEADERS)
                product_rows_count = len(product_rows)
                created.append(product_path)

            self._set_health_signal("server_csv", HEALTH_OK, f"Server CSV structure ready: {station_dir}")
            log_event(
                LOGGER,
                logging.INFO,
                "server_csv_structure_initialized",
                root=root,
                station_dir=station_dir,
                created_count=len(created),
                product_rows=product_rows_count,
            )
            if show_dialog:
                details = [
                    f"Server CSV path is writable:\n{station_dir}",
                    f"Created/verified {len(SERVER_CSV_FILENAMES)} dashboard CSV file(s).",
                    f"products.csv product rows seeded: {product_rows_count}",
                ]
                messagebox.showinfo("Server CSV", "\n\n".join(details), parent=self)
            return True
        except Exception as e:
            self._set_health_signal("server_csv", HEALTH_ERROR, "Path initialisation failed")
            LOGGER.exception(structured_message("server_csv_structure_init_failed", root=root, error=str(e)))
            if show_dialog:
                messagebox.showerror("Server CSV", f"Server CSV path initialisation failed:\n{e}", parent=self)
            return False

    def _sync_local_store_to_server_csv(self):
        if not self._logging_backend_uses_server_csv():
            self._set_health_signal("server_csv", HEALTH_UNKNOWN, "Disabled by logging backend")
            return True
        if self.local_store is None:
            self._set_health_signal("server_csv", HEALTH_ERROR, "Local store unavailable")
            return False

        started_at = time.perf_counter()
        root = self._server_csv_root_dir()
        if not root:
            self._set_health_signal("server_csv", HEALTH_WARNING, "No server CSV directory configured")
            LOGGER.warning(structured_message("server_csv_sync_skipped_no_directory"))
            return False

        try:
            scan_rows = normalize_scan_records(self.local_store.fetch_scan_rows())
            production_rows = self.local_store.fetch_production_rows()
            downtime_rows = self.local_store.fetch_downtime_rows()
            station_dir = self._server_csv_station_dir()

            lock = getattr(self, "_server_csv_lock", None) or threading.Lock()
            with lock:
                os.makedirs(station_dir, exist_ok=True)
                self._write_rows_to_csv_atomic(self._server_csv_path(SHEET_SCANS), scan_rows, SCAN_HEADERS)
                self._write_rows_to_csv_atomic(self._server_csv_path(SHEET_PRODUCTION), production_rows, PRODUCTION_HEADERS)
                self._write_rows_to_csv_atomic(self._server_csv_path(SHEET_DOWNTIME), downtime_rows, DOWNTIME_HEADERS)

            self._set_health_timestamp("last_successful_server_csv_write_at", datetime.now())
            self._set_health_signal("server_csv", HEALTH_OK, f"CSV export updated: {station_dir}")
            log_timing(
                LOGGER,
                logging.INFO,
                "server_csv_sync_complete",
                started_at,
                root=root,
                station_dir=station_dir,
                scans=len(scan_rows),
                production=len(production_rows),
                downtime=len(downtime_rows),
            )
            return True
        except Exception as e:
            self._set_health_signal("server_csv", HEALTH_ERROR, "CSV export failed")
            LOGGER.exception(
                structured_message(
                    "server_csv_sync_failed",
                    root=root,
                    station_dir=self._server_csv_station_dir(),
                    duration_ms=elapsed_ms(started_at),
                    error=str(e),
                )
            )
            return False

    def test_server_csv_directory(self, show_dialog=True):
        return self.initialize_server_csv_structure(show_dialog=show_dialog)

    def _load_server_csv_barcodes(self, today_only=False):
        root = self._server_csv_root_dir()
        if not root or not os.path.exists(root):
            return set()
        today = datetime.now().strftime("%Y-%m-%d")
        barcodes = set()
        pattern = os.path.join(root, "**", SERVER_CSV_FILENAMES[SHEET_SCANS])
        for csv_path in glob.iglob(pattern, recursive=True):
            try:
                for row in self._read_csv_records(csv_path):
                    timestamp = str(row.get("Timestamp", "") or "")
                    if today_only and not timestamp.startswith(today):
                        continue
                    barcode = self._normalize_barcode(row.get("Barcode", ""))
                    if barcode:
                        barcodes.add(barcode)
            except Exception:
                LOGGER.exception(structured_message("server_csv_barcode_load_failed", path=csv_path))
        return barcodes

    def _load_server_product_records(self):
        for csv_path in self._server_product_csv_paths():
            try:
                rows = self._read_csv_records(csv_path)
            except Exception:
                LOGGER.exception(structured_message("server_csv_product_load_failed", path=csv_path))
                continue
            if not rows:
                continue
            records = []
            for row in rows:
                code = str(row.get("Product Code", "") or row.get("Product_Code", "") or row.get("PC", "") or "").strip()
                if not code:
                    continue
                description = str(row.get("Description", "") or "").strip()
                barcode_display = str(row.get("Barcode Display", "") or row.get("Barc", "") or row.get("Barcode", "") or "").strip()
                expected_cycle = str(row.get("Expected Cycle", "") or row.get("Expected_Cycle", "") or "").strip()
                records.append(
                    {
                        "code": code,
                        "description": description,
                        "barcode": barcode_display,
                        "expected_cycle": expected_cycle,
                        "search": f"{code} {description} {barcode_display}".lower(),
                    }
                )
            if records:
                log_event(LOGGER, logging.INFO, "server_csv_products_loaded", path=csv_path, count=len(records))
                return records
        return []

    def _get_product_info_from_server_csv(self, product_code):
        target = str(product_code or "").strip().lower()
        if not target:
            return None
        records = self._load_server_product_records()
        for record in records:
            if record["code"].strip().lower() == target:
                expected_raw = str(record.get("expected_cycle", "") or "").replace(",", ".")
                try:
                    expected_cycle = float(expected_raw.split()[0])
                    expected_cycle_display = f"{expected_cycle:.2f} sec"
                except Exception:
                    expected_cycle_display = "N/A"
                return {
                    "description": record.get("description", ""),
                    "Barc": record.get("barcode", ""),
                    "PC": record.get("code", ""),
                    "Expected_Cycle": expected_cycle_display,
                }
        return None

    def get_product_info_from_sources(self, product_code):
        if not product_code:
            return None

        if self._logging_backend_uses_google():
            try:
                product_info = get_product_info(product_code)
                if product_info:
                    return product_info
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "product_info_google_lookup_failed",
                        product_code=product_code,
                    )
                )
                if getattr(self, "logging_backend", LOG_BACKEND_GOOGLE) == LOG_BACKEND_GOOGLE:
                    return None

        if self._logging_backend_uses_server_csv():
            product_info = self._get_product_info_from_server_csv(product_code)
            if product_info:
                return product_info

        return None

    def get_product_info_cached(self, product_code):
        return self.get_product_info_from_sources(product_code)

    def _style_excel_export_sheet(self, worksheet):
        style_excel_export_sheet(worksheet, PatternFill)

    def _export_local_store_to_excel(self):
        if self.local_store is None:
            self._set_health_signal("excel", HEALTH_ERROR, "Local store unavailable for export")
            return False

        try:
            scan_rows = self.local_store.fetch_scan_rows()
            production_rows = self.local_store.fetch_production_rows()
            downtime_rows = self.local_store.fetch_downtime_rows()

            scan_df = self._build_export_dataframe(scan_rows, SCAN_HEADERS, normalize_scans=True)
            production_df = self._build_export_dataframe(production_rows, PRODUCTION_HEADERS)
            downtime_df = self._build_export_dataframe(downtime_rows, DOWNTIME_HEADERS)

            with pd.ExcelWriter(self.excel_file, engine='openpyxl') as writer:
                scan_df.to_excel(writer, index=False, sheet_name=SHEET_SCANS)
                production_df.to_excel(writer, index=False, sheet_name='Production')
                downtime_df.to_excel(writer, index=False, sheet_name=SHEET_DOWNTIME)

                for worksheet in writer.sheets.values():
                    self._style_excel_export_sheet(worksheet)

            self.local_store.mark_all_excel_exported()
            self._set_excel_health_success("Excel export updated")
            self._set_local_store_health_success("Excel export checkpoint updated")
            log_event(
                LOGGER,
                logging.INFO,
                "excel_export_updated_from_local_store",
                scans=len(scan_rows),
                production=len(production_rows),
                downtime=len(downtime_rows),
                path=self.excel_file,
            )
            return True
        except Exception as e:
            try:
                self.local_store.mark_excel_export_failed(str(e))
            except Exception:
                LOGGER.exception(structured_message("local_store_excel_failure_mark_failed", db_path=self.local_db_file))
                self._set_health_signal("local_store", HEALTH_WARNING, "Excel failure mark failed")
            LOGGER.exception(
                structured_message(
                    "excel_export_from_local_store_failed",
                    excel_file=self.excel_file,
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("excel", HEALTH_ERROR, "Excel export failed")
            return False

    def initialize_excel_log(self):
        """Prepare Excel export and duplicate caches from the local event store."""
        started_at = time.perf_counter()
        self._bootstrap_local_store_from_excel()
        self._load_local_barcodes()
        self._export_local_store_to_excel()

        existing = set()
        if self._logging_backend_uses_server_csv():
            try:
                existing |= self._load_server_csv_barcodes(today_only=False)
                self._set_health_signal("server_csv", HEALTH_OK, "Barcode cache seeded")
            except Exception:
                LOGGER.exception(structured_message("server_csv_barcode_cache_seed_failed"))
                self._set_health_signal("server_csv", HEALTH_WARNING, "Barcode cache seed failed")

        if not self._logging_backend_uses_google():
            if not hasattr(self, 'scanned_barcodes') or self.scanned_barcodes is None:
                self.scanned_barcodes = set()
            self.scanned_barcodes |= existing
            if existing:
                self._set_health_signal("duplicate_check", HEALTH_OK, "Barcode cache seeded")
            try:
                print(f"[DupCheck] Cached barcodes loaded: {len(self.scanned_barcodes)}")
                log_event(LOGGER, logging.INFO, "barcode_cache_seed_complete", cached_count=len(self.scanned_barcodes))
            except Exception:
                pass
            log_timing(LOGGER, logging.INFO, "excel_log_initialized", started_at, excel_file=getattr(self, "excel_file", ""))
            return

        # Also load barcodes from Google Sheets to ensure global duplicate prevention
        try:
            existing = set(existing)
            # Prefer 'Scans' worksheet if present
            try:
                gs_scans = sheet.worksheet("Scans")
                values = gs_scans.get_all_values()
                if values:
                    header = [h.strip() for h in values[0]]
                    if 'Barcode' in header:
                        idx = header.index('Barcode')
                        for row in values[1:]:
                            if len(row) > idx and row[idx].strip():
                                existing.add(self._normalize_barcode(row[idx]))
            except gspread.exceptions.WorksheetNotFound:
                pass

            # Also check legacy/default worksheet 'Sheet1' if present
            try:
                if any(ws.title == 'Sheet1' for ws in sheet.worksheets()):
                    legacy_ws = sheet.worksheet('Sheet1')
                    values = legacy_ws.get_all_values()
                    if values:
                        header = [h.strip() for h in values[0]]
                        if 'Barcode' in header:
                            idx = header.index('Barcode')
                            rows_iter = values[1:]
                        else:
                            # No header row – use third column (index 2) and include first row
                            idx = 2 if len(values[0]) > 2 else None
                            rows_iter = values  # include first row
                        if idx is not None:
                            for row in rows_iter:
                                if len(row) > idx and row[idx].strip():
                                    existing.add(self._normalize_barcode(row[idx]))
            except Exception as e:
                print(f"Warning loading barcodes from Sheet1: {e}")
                LOGGER.exception(
                    structured_message(
                        "google_sheets_legacy_barcode_load_failed",
                        worksheet="Sheet1",
                    )
                )

            if not hasattr(self, 'scanned_barcodes') or self.scanned_barcodes is None:
                self.scanned_barcodes = set()
            self.scanned_barcodes |= existing
            self._set_health_signal("duplicate_check", HEALTH_OK, "Barcode cache seeded")
        except Exception as e:
            print(f"Error loading barcodes from Google Sheets: {e}")
            LOGGER.exception(
                structured_message(
                    "google_sheets_barcode_cache_seed_failed",
                    worksheets=["Scans", "Sheet1"],
                )
            )
            self._set_health_signal("google_sheets", HEALTH_WARNING, "Barcode cache seed failed")
            self._set_health_signal("duplicate_check", HEALTH_WARNING, "Barcode cache seed incomplete")
        finally:
            try:
                print(f"[DupCheck] Cached barcodes loaded: {len(self.scanned_barcodes)}")
                log_event(LOGGER, logging.INFO, "barcode_cache_seed_complete", cached_count=len(self.scanned_barcodes))
            except Exception:
                pass
        log_timing(LOGGER, logging.INFO, "excel_log_initialized", started_at, excel_file=getattr(self, "excel_file", ""))

    def sync_all_to_google_sheets(self):
        """Sync pending local events to downstream sinks."""
        started_at = time.perf_counter()
        sync_batch_id = make_correlation_id("sync")
        overall_success = True
        uses_google = self._logging_backend_uses_google()
        uses_server_csv = self._logging_backend_uses_server_csv()
        log_event(
            LOGGER,
            logging.INFO,
            "downstream_sync_batch_begin",
            sync_batch_id=sync_batch_id,
            logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
            google_enabled=uses_google,
            server_csv_enabled=uses_server_csv,
        )

        if not self._export_local_store_to_excel():
            overall_success = False

        if uses_server_csv and not self._sync_local_store_to_server_csv():
            overall_success = False

        if uses_google:
            try:
                initialize_google_sheets()
            except Exception:
                overall_success = False
                self._set_health_signal("google_sheets", HEALTH_ERROR, "Google init failed")
                self._set_health_signal("google_write", HEALTH_ERROR, "Google init failed")
            else:
                if not self._sync_pending_scan_events_to_google():
                    overall_success = False

                if not self._sync_pending_production_events_to_google():
                    overall_success = False

                if not self._sync_pending_downtime_events_to_google():
                    overall_success = False
        else:
            self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Disabled by logging backend")
            self._set_health_signal("google_write", HEALTH_UNKNOWN, "Disabled by logging backend")

        if overall_success:
            if uses_google:
                self._set_health_signal("google_sheets", HEALTH_OK, "Sync completed")
                self._set_health_signal("google_write", HEALTH_OK, "Sync completed")
            if uses_server_csv:
                self._set_health_signal("server_csv", HEALTH_OK, "Sync completed")
        else:
            if uses_google:
                self._set_health_signal("google_write", HEALTH_WARNING, "Sync incomplete")
        log_timing(
            LOGGER,
            logging.INFO,
            "downstream_sync_batch_complete",
            started_at,
            sync_batch_id=sync_batch_id,
            logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
            google_enabled=uses_google,
            server_csv_enabled=uses_server_csv,
            outcome="success" if overall_success else "partial_failure",
        )
        return overall_success

    def _sync_pending_scan_events_to_google(self):
        if self.local_store is None:
            self._set_health_signal("google_write", HEALTH_ERROR, "Local store unavailable")
            return False

        overall_success = True
        events = self.local_store.fetch_pending_scan_google_events()
        for event_row in events:
            event_id = event_row.get("_event_id", "")
            scans_synced = bool(event_row.get("_google_scans_synced"))
            sheet1_synced = bool(event_row.get("_google_sheet1_synced"))
            scan_errors = {}
            scans_ok = scans_synced
            sheet1_ok = sheet1_synced

            if not scans_synced:
                try:
                    scans_result = self._append_map_to_sheet(
                        SHEET_SCANS,
                        event_row,
                        SCAN_HEADERS,
                        event_id=event_id,
                    )
                    scans_ok = bool(scans_result.get("ok"))
                    if scans_ok:
                        self.local_store.mark_scan_google_synced(
                            event_id,
                            "scans",
                            row_ref=scans_result.get("row_ref"),
                        )
                    else:
                        scan_errors[SHEET_SCANS] = "Append failed"
                        self.local_store.mark_scan_google_failed(event_id, "scans", "Append failed")
                except Exception as e:
                    scan_errors[SHEET_SCANS] = str(e)
                    self.local_store.mark_scan_google_failed(event_id, "scans", str(e))
                    LOGGER.exception(
                        structured_message(
                            "google_sheets_scan_sync_failed",
                            event_id=event_id,
                            worksheet=SHEET_SCANS,
                        )
                    )

            if not sheet1_synced:
                try:
                    sheet1_result = self._append_map_to_sheet(
                        SHEET_SCANS_LEGACY,
                        event_row,
                        SCAN_HEADERS,
                        event_id=event_id,
                    )
                    sheet1_ok = bool(sheet1_result.get("ok"))
                    if sheet1_ok:
                        self.local_store.mark_scan_google_synced(
                            event_id,
                            "sheet1",
                            row_ref=sheet1_result.get("row_ref"),
                        )
                    else:
                        scan_errors[SHEET_SCANS_LEGACY] = "Append failed"
                        self.local_store.mark_scan_google_failed(event_id, "sheet1", "Append failed")
                except Exception as e:
                    scan_errors[SHEET_SCANS_LEGACY] = str(e)
                    self.local_store.mark_scan_google_failed(event_id, "sheet1", str(e))
                    LOGGER.exception(
                        structured_message(
                            "google_sheets_scan_sync_failed",
                            event_id=event_id,
                            worksheet=SHEET_SCANS_LEGACY,
                        )
                    )

            google_detail = self._describe_google_persistence_outcome(scans_ok, sheet1_ok)
            if scans_ok or sheet1_ok:
                self._set_health_timestamp("last_successful_google_write_at", datetime.now())
            if scans_ok and sheet1_ok:
                self._set_health_signal("google_sheets", HEALTH_OK, "Connected")
                self._set_health_signal("google_write", HEALTH_OK, "Scans and Sheet1 appended")
            elif scans_ok or sheet1_ok:
                overall_success = False
                self._set_health_signal("google_sheets", HEALTH_WARNING, "Partial scan append")
                self._set_health_signal("google_write", HEALTH_WARNING, google_detail)
            else:
                overall_success = False
                self._set_health_signal("google_sheets", HEALTH_ERROR, "Scan append failed")
                self._set_health_signal("google_write", HEALTH_ERROR, "Scans and Sheet1 failed")
                LOGGER.error(
                    structured_message(
                        "scan_local_event_google_sync_failed",
                        event_id=event_id,
                        errors=scan_errors,
                    )
                )

        self._update_google_sync_backlog_health("Scans and Sheet1 synced")
        return overall_success

    def _sync_pending_production_events_to_google(self):
        if self.local_store is None:
            return False

        overall_success = True
        for event_row in self.local_store.fetch_pending_production_google_events():
            event_id = event_row.get("_event_id", "")
            try:
                write_result = self._append_map_to_sheet(
                    'Production',
                    event_row,
                    PRODUCTION_HEADERS,
                    event_id=event_id,
                )
                write_ok = bool(write_result.get("ok"))
                if write_ok:
                    self.local_store.mark_production_google_synced(
                        event_id,
                        row_ref=write_result.get("row_ref"),
                    )
                else:
                    overall_success = False
                    self.local_store.mark_production_google_failed(event_id, "Append failed")
            except Exception as e:
                overall_success = False
                self.local_store.mark_production_google_failed(event_id, str(e))
                LOGGER.exception(
                    structured_message(
                        "production_local_event_google_sync_failed",
                        event_id=event_id,
                    )
                )
        self._update_google_sync_backlog_health("Production events synced")
        return overall_success

    def _sync_pending_downtime_events_to_google(self):
        if self.local_store is None:
            return False

        overall_success = True
        for event_row in self.local_store.fetch_pending_downtime_google_events():
            event_id = event_row.get("_event_id", "")
            try:
                write_result = self._append_map_to_sheet(
                    SHEET_DOWNTIME,
                    event_row,
                    DOWNTIME_HEADERS,
                    event_id=event_id,
                )
                write_ok = bool(write_result.get("ok"))
                if write_ok:
                    self.local_store.mark_downtime_google_synced(
                        event_id,
                        row_ref=write_result.get("row_ref"),
                    )
                else:
                    overall_success = False
                    self.local_store.mark_downtime_google_failed(event_id, "Append failed")
            except Exception as e:
                overall_success = False
                self.local_store.mark_downtime_google_failed(event_id, str(e))
                LOGGER.exception(
                    structured_message(
                        "downtime_local_event_google_sync_failed",
                        event_id=event_id,
                    )
                )
        self._update_google_sync_backlog_health("Downtime events synced")
        return overall_success
            
    def sync_to_google_sheets(self, df):
        """Legacy compatibility shim for older dataframe-based callers."""
        if not ENABLE_LEGACY_DATAFRAME_SYNC_WRAPPER:
            LOGGER.warning(structured_message("legacy_dataframe_sync_disabled"))
            self._set_health_signal("google_write", HEALTH_WARNING, "Legacy sync wrapper disabled")
            return False
        row_count = len(df.index) if hasattr(df, "index") else None
        column_count = len(df.columns) if hasattr(df, "columns") else None
        LOGGER.warning(
            structured_message(
                "legacy_dataframe_sync_redirected",
                row_count=row_count,
                column_count=column_count,
            )
        )
        return self.sync_all_to_google_sheets()

    def log_scan_to_excel(self, barcode, status='Scanned', notes='', is_rework=False, cycle_time_seconds=None, scan_id=""):
        """Durably store a scan locally, then sync downstream sinks in the background."""
        try:
            started_at = time.perf_counter()
            now = datetime.now()
            product_code = self.product_var.get()
            batch = f"{barcode[:5]}{now.strftime('%d%m')}"
            normalized_barcode = self._normalize_barcode(barcode)

            # Get description from cache or UI
            description = self.description_var.get()
            if not description and product_code:
                # Try to get from cache if UI doesn't have it yet
                product_info = self.get_product_info_cached(product_code)
                if product_info:
                    description = product_info.get('Description', '')

            if cycle_time_seconds is None:
                cycle_time_seconds = self._calculate_scan_cycle_time(now)
            cycle_time = max(0.0, float(cycle_time_seconds or 0.0))
            status = normalize_scan_status(status, is_rework=is_rework)
            
            # Canonical schema emits Product Code and Workcenter, but we still keep
            # Product_Code alias support when writing into legacy-shaped sheets.
            new_row = build_scan_row(
                timestamp=now,
                product_code=product_code,
                barcode=barcode,
                batch=batch,
                cycle_time_seconds=cycle_time,
                status=status,
                description=description,
                operator=self.operator_name_var.get() or 'Unknown',
                notes=notes,
                is_rework=is_rework,
                workcenter=getattr(self, 'current_workcenter', ''),
            )

            event_id, inserted = self._require_local_store().append_scan_event(
                new_row,
                normalized_barcode=normalized_barcode,
            )
            if not inserted:
                LOGGER.warning(
                    structured_message(
                        "scan_local_duplicate_commit_blocked",
                        barcode=normalized_barcode,
                        status=status,
                        event_id=event_id,
                    )
                )
                self._set_scan_write_health("Scan already stored locally", local_ok=False)
                return False

            self._set_local_store_health_success("Scan committed locally")
            self._set_scan_write_health("Scan committed locally", local_ok=True)

            if status == SCAN_STATUS_SCANNED:
                with self._barcode_cache_lock:
                    self.scanned_barcodes.add(normalized_barcode)
                    self._barcode_cache.add(normalized_barcode)
                    self._last_barcode_check = normalized_barcode
                    self._last_barcode_result = True

            log_event(
                LOGGER,
                logging.INFO,
                "scan_local_commit_complete",
                barcode=normalized_barcode,
                scan_id=scan_id,
                event_id=event_id,
                status=status,
                is_rework=is_rework,
                cycle_time_seconds=round(cycle_time, 2),
                duration_ms=elapsed_ms(started_at),
            )

            try:
                thread = threading.Thread(
                    target=self._async_log_scan,
                    args=(event_id, barcode, new_row, status, notes, is_rework, scan_id),
                    daemon=True
                )
                thread.start()
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "scan_downstream_worker_start_failed",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                    )
                )
                self._set_health_signal("excel", HEALTH_WARNING, "Local scan stored; export worker failed")
                self._set_health_signal("google_write", HEALTH_WARNING, "Local scan stored; sync worker failed")

            return True

        except Exception as e:
            print(f"Error in log_scan_to_excel: {e}")
            LOGGER.exception(
                structured_message(
                    "scan_log_request_failed",
                    barcode=barcode,
                    scan_id=scan_id,
                    status=status,
                    db_path=self.local_db_file,
                    excel_file=getattr(self, 'excel_file', ''),
                )
            )
            self._set_health_signal("scan_write", HEALTH_ERROR, "Local scan commit failed")
            self._set_health_signal("local_store", HEALTH_ERROR, "Scan commit failed")
            return False

    def _async_log_scan(self, event_id, barcode, new_row, status, notes, is_rework, scan_id=""):
        """Background task to export locally committed scans to Excel and Google Sheets."""
        started_at = time.perf_counter()
        normalized_barcode = self._normalize_barcode(barcode)
        excel_ok = False
        server_csv_ok = True
        scans_ok = False
        sheet1_ok = False
        sheet_errors = {}

        try:
            cycle_time = float(str(new_row.get('Cycle time', '0')).replace(' s', '').strip()) if 'Cycle time' in new_row else 0.0
        except (TypeError, ValueError, AttributeError):
            cycle_time = 0.0

        log_event(
            LOGGER,
            logging.INFO,
            "scan_log_worker_started",
            barcode=normalized_barcode,
            scan_id=scan_id,
            event_id=event_id,
            status=status,
            is_rework=is_rework,
        )

        try:
            excel_ok = self._export_local_store_to_excel()
            if self._logging_backend_uses_server_csv():
                server_csv_ok = self._sync_local_store_to_server_csv()

            if not self._logging_backend_uses_google():
                self._set_health_signal("google_sheets", HEALTH_UNKNOWN, "Disabled by logging backend")
                self._set_health_signal("google_write", HEALTH_UNKNOWN, "Disabled by logging backend")
                if excel_ok and server_csv_ok:
                    log_event(
                        LOGGER,
                        logging.INFO,
                        "scan_log_completed",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                        status=status,
                        excel_ok=excel_ok,
                        server_csv_ok=server_csv_ok,
                        google_enabled=False,
                        cycle_time_seconds=round(cycle_time, 2),
                        duration_ms=elapsed_ms(started_at),
                    )
                else:
                    LOGGER.warning(
                        structured_message(
                            "scan_log_partial_persistence",
                            barcode=normalized_barcode,
                            scan_id=scan_id,
                            event_id=event_id,
                            status=status,
                            excel_ok=excel_ok,
                            server_csv_ok=server_csv_ok,
                            google_enabled=False,
                            cycle_time_seconds=round(cycle_time, 2),
                            duration_ms=elapsed_ms(started_at),
                        )
                    )
                return excel_ok or server_csv_ok

            try:
                scans_result = self._append_map_to_sheet(
                    SHEET_SCANS,
                    new_row,
                    SCAN_HEADERS,
                    event_id=event_id,
                )
                scans_ok = bool(scans_result.get("ok"))
                if not scans_ok:
                    sheet_errors[SHEET_SCANS] = "Append failed"
                    self.local_store.mark_scan_google_failed(event_id, "scans", "Append failed")
                else:
                    self.local_store.mark_scan_google_synced(
                        event_id,
                        "scans",
                        row_ref=scans_result.get("row_ref"),
                    )
            except Exception as e:
                print(f"Error updating {SHEET_SCANS} worksheet: {e}")
                LOGGER.exception(
                    structured_message(
                        "google_sheets_scan_append_failed",
                        barcode=barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                        worksheet=SHEET_SCANS,
                        status=status,
                    )
                )
                sheet_errors[SHEET_SCANS] = str(e)
                try:
                    self.local_store.mark_scan_google_failed(event_id, "scans", str(e))
                except Exception:
                    self._set_health_signal("local_store", HEALTH_WARNING, "Scan sync failure mark failed")

            try:
                sheet1_result = self._append_map_to_sheet(
                    SHEET_SCANS_LEGACY,
                    new_row,
                    SCAN_HEADERS,
                    event_id=event_id,
                )
                sheet1_ok = bool(sheet1_result.get("ok"))
                if not sheet1_ok:
                    sheet_errors[SHEET_SCANS_LEGACY] = "Append failed"
                    self.local_store.mark_scan_google_failed(event_id, "sheet1", "Append failed")
                else:
                    self.local_store.mark_scan_google_synced(
                        event_id,
                        "sheet1",
                        row_ref=sheet1_result.get("row_ref"),
                    )
            except Exception as e:
                print(f"Error updating {SHEET_SCANS_LEGACY} worksheet: {e}")
                LOGGER.exception(
                    structured_message(
                        "google_sheets_scan_append_failed",
                        barcode=barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                        worksheet=SHEET_SCANS_LEGACY,
                        status=status,
                    )
                )
                sheet_errors[SHEET_SCANS_LEGACY] = str(e)
                try:
                    self.local_store.mark_scan_google_failed(event_id, "sheet1", str(e))
                except Exception:
                    self._set_health_signal("local_store", HEALTH_WARNING, "Scan sync failure mark failed")

            google_detail = self._describe_google_persistence_outcome(scans_ok, sheet1_ok)
            if scans_ok or sheet1_ok:
                self._set_health_timestamp("last_successful_google_write_at", datetime.now())
            if scans_ok and sheet1_ok:
                self._set_health_signal("google_sheets", HEALTH_OK, "Connected")
                self._set_health_signal("google_write", HEALTH_OK, "Scans and Sheet1 appended")
            elif scans_ok or sheet1_ok:
                self._set_health_signal("google_sheets", HEALTH_WARNING, "Partial scan append")
                self._set_health_signal("google_write", HEALTH_WARNING, google_detail)
            else:
                self._set_health_signal("google_sheets", HEALTH_ERROR, "Scan append failed")
                self._set_health_signal("google_write", HEALTH_ERROR, "Scans and Sheet1 failed")

            self._update_google_sync_backlog_health("Scans and Sheet1 synced")

            if excel_ok and server_csv_ok and scans_ok and sheet1_ok:
                log_event(
                    LOGGER,
                    logging.INFO,
                    "scan_log_completed",
                    barcode=normalized_barcode,
                    scan_id=scan_id,
                    event_id=event_id,
                    status=status,
                    excel_ok=excel_ok,
                    server_csv_ok=server_csv_ok,
                    scans_ok=scans_ok,
                    sheet1_ok=sheet1_ok,
                    cycle_time_seconds=round(cycle_time, 2),
                    duration_ms=elapsed_ms(started_at),
                )
            elif excel_ok or server_csv_ok or scans_ok or sheet1_ok:
                LOGGER.warning(
                    structured_message(
                        "scan_log_partial_persistence",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                        status=status,
                        excel_ok=excel_ok,
                        server_csv_ok=server_csv_ok,
                        scans_ok=scans_ok,
                        sheet1_ok=sheet1_ok,
                        errors=sheet_errors,
                        cycle_time_seconds=round(cycle_time, 2),
                        duration_ms=elapsed_ms(started_at),
                    )
                )
            else:
                LOGGER.error(
                    structured_message(
                        "scan_log_persistence_failed",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        event_id=event_id,
                        status=status,
                        excel_ok=excel_ok,
                        server_csv_ok=server_csv_ok,
                        scans_ok=scans_ok,
                        sheet1_ok=sheet1_ok,
                        errors=sheet_errors,
                        cycle_time_seconds=round(cycle_time, 2),
                        duration_ms=elapsed_ms(started_at),
                    )
                )

            return excel_ok or server_csv_ok or scans_ok or sheet1_ok

        except Exception as e:
            print(f"Error in _async_log_scan: {e}")
            LOGGER.exception(
                structured_message(
                    "async_scan_log_failed",
                    barcode=barcode,
                    scan_id=scan_id,
                    event_id=event_id,
                    status=status,
                    db_path=self.local_db_file,
                    excel_file=getattr(self, 'excel_file', ''),
                    duration_ms=elapsed_ms(started_at),
                )
            )
            self._set_health_signal("excel", HEALTH_ERROR, "Async scan logging failed")
            self._set_health_signal("google_sheets", HEALTH_ERROR, "Async scan logging failed")
            self._set_health_signal("google_write", HEALTH_ERROR, "Async scan logging failed")
            return False

    def _commit_local_production_event(self, row):
        event_id, inserted = self._require_local_store().append_production_event(row)
        if not inserted:
            raise RuntimeError("Production event already stored locally.")
        self._set_local_store_health_success("Production event committed locally")
        return event_id

    def _commit_local_downtime_event(self, row):
        event_id, inserted = self._require_local_store().append_downtime_event(row)
        if not inserted:
            raise RuntimeError("Downtime event already stored locally.")
        self._set_local_store_health_success("Downtime event committed locally")
        return event_id

    def _async_sync_production_event(self, event_id):
        try:
            sync_ok = self.sync_all_to_google_sheets()
            if sync_ok:
                log_event(LOGGER, logging.INFO, "production_event_sync_completed", event_id=event_id)
            else:
                LOGGER.warning(
                    structured_message(
                        "production_event_sync_incomplete",
                        event_id=event_id,
                        logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
                    )
                )
        except Exception:
            LOGGER.exception(structured_message("production_event_sync_failed", event_id=event_id))
            self._set_health_signal("excel", HEALTH_ERROR, "Production sync failed")
            self._set_health_signal("google_write", HEALTH_ERROR, "Production sync failed")

    def _async_sync_downtime_event(self, event_id):
        try:
            sync_ok = self.sync_all_to_google_sheets()
            if sync_ok:
                log_event(LOGGER, logging.INFO, "downtime_event_sync_completed", event_id=event_id)
            else:
                LOGGER.warning(
                    structured_message(
                        "downtime_event_sync_incomplete",
                        event_id=event_id,
                        logging_backend=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE),
                    )
                )
        except Exception:
            LOGGER.exception(structured_message("downtime_event_sync_failed", event_id=event_id))
            self._set_health_signal("excel", HEALTH_ERROR, "Downtime sync failed")
            self._set_health_signal("google_write", HEALTH_ERROR, "Downtime sync failed")

    def _update_barcode_cache_worker(self):
        """Background worker to keep the barcode cache updated"""
        while not self._stop_cache_update.is_set():
            try:
                self._update_barcode_cache()
            except Exception as e:
                print(f"Error updating barcode cache: {e}")
                LOGGER.exception(structured_message("barcode_cache_worker_failed"))
            
            # Sleep for 5 minutes before next update
            self._stop_cache_update.wait(300)
    
    def _update_barcode_cache(self):
        """Update the barcode cache from Google Sheets"""
        try:
            with self._barcode_cache_lock:
                # Only update if cache is older than TTL
                current_time = time.time()
                if current_time - self._barcode_cache_last_update < self._barcode_cache_ttl:
                    return
                
                print("[BarcodeCache] Updating barcode cache...")
                if self._logging_backend_uses_server_csv() and not self._logging_backend_uses_google():
                    new_cache = self._load_server_csv_barcodes(today_only=True) or self._load_server_csv_barcodes(today_only=False)
                    self._barcode_cache = new_cache
                    self._barcode_cache_last_update = current_time
                    self._set_health_signal("duplicate_check", HEALTH_OK, "Server CSV cache refreshed")
                    log_event(LOGGER, logging.INFO, "server_csv_barcode_cache_refreshed", count=len(new_cache))
                    return

                ws = sheet.worksheet("Scans")
                
                # Get today's date in the same format as in the sheet
                today = datetime.now().strftime("%Y-%m-%d")
                
                # First, try to get just today's barcodes (faster)
                try:
                    records = ws.get_all_records()
                    new_cache = {self._normalize_barcode(record.get('Barcode', '')) 
                               for record in records 
                               if record.get('Barcode') and str(record.get('Timestamp', '')).startswith(today)}
                    
                    # If we found today's barcodes, use them
                    if new_cache:
                        self._barcode_cache = new_cache
                        self._barcode_cache_last_update = current_time
                        print(f"[BarcodeCache] Updated with {len(new_cache)} today's barcodes")
                        self._set_health_signal("duplicate_check", HEALTH_OK, "Cache refreshed")
                        return
                        
                except Exception as e:
                    print(f"[BarcodeCache] Error getting today's barcodes: {e}")
                    LOGGER.exception(
                        structured_message(
                            "barcode_cache_today_load_failed",
                            worksheet="Scans",
                        )
                    )
                
                # Fallback: Get all barcodes (slower)
                try:
                    records = ws.get_all_records()
                    self._barcode_cache = {self._normalize_barcode(record.get('Barcode', '')) 
                                         for record in records if record.get('Barcode')}
                    self._barcode_cache_last_update = current_time
                    print(f"[BarcodeCache] Updated with {len(self._barcode_cache)} total barcodes")
                    self._set_health_signal("duplicate_check", HEALTH_OK, "Cache refreshed")
                    
                except Exception as e:
                    print(f"[BarcodeCache] Error getting all barcodes: {e}")
                    LOGGER.exception(
                        structured_message(
                            "barcode_cache_full_load_failed",
                            worksheet="Scans",
                        )
                    )
                    self._set_health_timestamp("last_duplicate_check_failure_at", datetime.now())
                    self._set_health_signal("duplicate_check", HEALTH_WARNING, "Cache refresh failed")
                    
        except Exception as e:
            print(f"[BarcodeCache] Error in cache update: {e}")
            LOGGER.exception(structured_message("barcode_cache_update_failed"))
            self._set_health_timestamp("last_duplicate_check_failure_at", datetime.now())
            self._set_health_signal("duplicate_check", HEALTH_WARNING, "Cache update failed")
    
    def is_duplicate_barcode(self, barcode):
        """Check if a barcode has been scanned before with optimized caching"""
        if not barcode:
            return False
            
        b = self._normalize_barcode(barcode)

        with self._barcode_cache_lock:
            cached_duplicate, duplicate_source, temporal_cache_hit = duplicate_cache_lookup(
                b,
                self.scanned_barcodes,
                self._barcode_cache,
                self._last_barcode_check,
                self._last_barcode_result,
            )
            last_barcode_result = self._last_barcode_result
            barcode_cache_last_update = self._barcode_cache_last_update

        # 1-3. Check in-memory, sheet cache, and temporal cache before slower fallbacks.
        if cached_duplicate is True:
            if duplicate_source:
                log_event(LOGGER, logging.INFO, "duplicate_barcode_detected", barcode=b, source=duplicate_source)
            return True
        if temporal_cache_hit:
            return last_barcode_result
            
        # 4. If cache is empty or stale, trigger an update in the background
        current_time = time.time()
        if should_refresh_barcode_cache(barcode_cache_last_update, self._barcode_cache_ttl, current_time):
            threading.Thread(target=self._update_barcode_cache, daemon=True).start()

        # 5. Check the durable local store before any remote lookup.
        try:
            if self.local_store and self.local_store.scan_exists(b):
                with self._barcode_cache_lock:
                    self.scanned_barcodes.add(b)
                    self._barcode_cache.add(b)
                    self._last_barcode_check = b
                    self._last_barcode_result = True
                self._set_local_store_health_success("Duplicate lookup succeeded")
                log_event(LOGGER, logging.INFO, "duplicate_barcode_detected", barcode=b, source="local_store")
                return True
        except Exception:
            LOGGER.exception(
                structured_message(
                    "duplicate_barcode_local_lookup_failed",
                    barcode=b,
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_WARNING, "Duplicate lookup failed")
            self._set_health_timestamp("last_duplicate_check_failure_at", datetime.now())
            self._set_health_signal("duplicate_check", HEALTH_WARNING, "Local lookup failed")

        # 6. Check Server CSV directly when enabled.
        if self._logging_backend_uses_server_csv():
            try:
                server_barcodes = self._load_server_csv_barcodes(today_only=False)
                if b in server_barcodes:
                    with self._barcode_cache_lock:
                        self._barcode_cache.add(b)
                        self.scanned_barcodes.add(b)
                        self._last_barcode_check = b
                        self._last_barcode_result = True
                    log_event(LOGGER, logging.INFO, "duplicate_barcode_detected", barcode=b, source="server_csv")
                    return True
            except Exception:
                LOGGER.exception(structured_message("duplicate_barcode_server_csv_lookup_failed", barcode=b))
                self._set_health_timestamp("last_duplicate_check_failure_at", datetime.now())
                self._set_health_signal("duplicate_check", HEALTH_WARNING, "Server CSV lookup failed")

        if not self._logging_backend_uses_google():
            with self._barcode_cache_lock:
                self._last_barcode_check = b
                self._last_barcode_result = False
            return False

        # 7. Check Google Sheets directly as a final compatibility fallback.
        is_duplicate = False
        try:
            # Try to find the barcode in the Scans worksheet
            ws = sheet.worksheet("Scans")
            result = ws.find(b, in_column=3)  # Column 3 is Barcode
            is_duplicate = result is not None
            
            # If not found in Scans, try Sheet1 as fallback
            if not is_duplicate:
                try:
                    ws = sheet.worksheet("Sheet1")
                    result = ws.find(b, in_column=3)  # Column 3 is Barcode
                    is_duplicate = result is not None
                except gspread.exceptions.WorksheetNotFound:
                    pass
            
            # Update caches if duplicate found
            if is_duplicate:
                with self._barcode_cache_lock:
                    self._barcode_cache.add(b)
                    # Also add to scanned_barcodes for faster future lookups
                    self.scanned_barcodes.add(b)
                log_event(LOGGER, logging.INFO, "duplicate_barcode_detected", barcode=b, source="google_sheets")
            
            # Update temporal cache
            with self._barcode_cache_lock:
                self._last_barcode_check = b
                self._last_barcode_result = is_duplicate
            self._set_health_signal("duplicate_check", HEALTH_OK, "Lookup succeeded")
            
        except Exception as e:
            print(f"[DuplicateCheck] Error checking barcode in Google Sheets: {e}")
            LOGGER.exception(
                structured_message(
                    "duplicate_barcode_check_failed",
                    barcode=b,
                    worksheets=["Scans", "Sheet1"],
                )
            )
            self._set_health_timestamp("last_duplicate_check_failure_at", datetime.now())
            self._set_health_signal("duplicate_check", HEALTH_WARNING, "Direct lookup failed")
            # If we can't check Google Sheets, be safe and don't block the scan
            is_duplicate = False
        
        return is_duplicate
            
    #except Exception as e:
            #print(f"[BarcodeCheck] Error checking barcode: {e}")
            #return False

    def _submit_duplicate_rework_scan(self, barcode, notes="", submission_state=None):
        if submission_state is not None:
            if submission_state.get("started"):
                return False
            submission_state["started"] = True

        notes_text = notes or "Marked as reworked"
        log_event(
            LOGGER,
            logging.INFO,
            "duplicate_popup_rework_print_requested",
            barcode=self._normalize_barcode(barcode),
            notes_provided=bool(str(notes or "").strip()),
        )
        return self.handle_scan(
            None,
            increment_count=False,
            barcode_override=barcode,
            status=SCAN_STATUS_REWORKED,
            notes=notes_text,
            is_rework=True,
            allow_duplicate_prompt=False,
            print_label_on_accept=True,
        )

    def handle_duplicate_barcode(self, barcode):
        """Show popup for duplicate barcode and handle user choice"""
        # Create popup window
        popup = ctk.CTkToplevel(self)
        popup.title("Duplicate Barcode Detected")
        
        # Set theme colors to match main application
        bg_color = "#2b2b2b"  # Dark theme background
        fg_color = "#333333"  # Slightly lighter than background
        text_color = "#ffffff"  # White text
        accent_color = "#1f6aa5"  # Blue accent color
        hover_color = "#144870"  # Darker blue for hover
        
        # Configure window
        popup.configure(fg_color=bg_color)
        popup.geometry("500x400")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()
        
        # Center the popup on screen
        popup.update_idletasks()
        width = 500
        height = 400
        x = (popup.winfo_screenwidth() // 2) - (width // 2)
        y = (popup.winfo_screenheight() // 2) - (height // 2)
        popup.geometry(f'{width}x{height}+{x}+{y}')
        
        # Main container frame
        container = ctk.CTkFrame(popup, fg_color=fg_color, corner_radius=10)
        container.pack(padx=20, pady=20, fill="both", expand=True)
        
        # Title
        title = ctk.CTkLabel(
            container,
            text="DUPLICATE BARCODE SCANNED",
            font=("Arial", 16, "bold"),
            text_color="#4fc3f7"  # Light blue for headers
        )
        title.pack(pady=(20, 10))
        
        # Divider line
        ctk.CTkFrame(
            container,
            height=2,
            fg_color="#4a4a4a"  # Dark gray divider
        ).pack(fill="x", padx=20, pady=5)
        
        # Message
        msg = f"The barcode {barcode} has already been scanned.\n\nHow would you like to proceed?"
        label = ctk.CTkLabel(
            container,
            text=msg,
            justify="center",
            wraplength=400,
            font=("Arial", 14),
            text_color=text_color
        )
        label.pack(pady=(15, 20), padx=30, anchor="center")
        
        # Notes frame
        notes_frame = ctk.CTkFrame(container, fg_color="transparent")
        notes_frame.pack(pady=(0, 20), padx=30, fill="x")
        
        notes_label = ctk.CTkLabel(
            notes_frame,
            text="Additional Notes:",
            font=("Arial", 12, "bold"),
            text_color="#4fc3f7",  # Light blue for labels
            anchor="w"
        )
        notes_label.pack(fill="x")
        
        notes_var = ctk.StringVar()
        notes_entry = ctk.CTkEntry(
            notes_frame,
            textvariable=notes_var,
            placeholder_text="Enter any notes about this rework...",
            height=80,
            corner_radius=5,
            fg_color="#3a3a3a",  # Slightly lighter than container
            border_width=1,
            border_color="#5a5a5a",
            text_color=text_color,
            placeholder_text_color="#888888"
        )
        notes_entry.pack(fill="x", pady=(5, 0))
        
        # Buttons frame
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(pady=(10, 20), padx=30, fill="x")
        
        rework_submission_state = {"started": False}

        def mark_as_reworked():
            if rework_submission_state.get("started"):
                return
            try:
                rework_btn.configure(state="disabled", text="Printing Rework...")
            except Exception:
                pass

            notes = notes_var.get() or "Marked as reworked"
            popup.destroy()
            accepted = self._submit_duplicate_rework_scan(
                barcode,
                notes,
                submission_state=rework_submission_state,
            )
            if accepted:
                messagebox.showinfo("Success", f"Barcode {barcode} marked as reworked and sent to print.")
            else:
                messagebox.showerror("Rework Not Logged", f"Barcode {barcode} could not be marked as reworked.")
            self._schedule_scan_focus(force=True, attempts=4)
        
        def cancel_scan():
            log_event(
                LOGGER,
                logging.INFO,
                "duplicate_popup_cancelled",
                barcode=self._normalize_barcode(barcode),
            )
            popup.destroy()
            self._schedule_scan_focus()
            
        # Mark as Reworked button
        rework_btn = ctk.CTkButton(
            btn_frame, 
            text="Mark as Reworked",
            command=mark_as_reworked,
            fg_color=accent_color,
            hover_color=hover_color,
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=5,
            text_color="white"
        )
        rework_btn.pack(side="left", expand=True, padx=(0, 10))
        
        # Cancel button
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel Scan",
            command=cancel_scan,
            fg_color="#5a5a5a",  # Dark gray
            hover_color="#6a6a6a",  # Slightly lighter on hover
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=5,
            text_color="white"
        )
        cancel_btn.pack(side="right", expand=True)
        
        # Make sure the popup is on top
        popup.lift()
        popup.focus_force()
        
        # Bind Enter key to mark as reworked
        popup.bind('<Return>', lambda e: mark_as_reworked())
        # Bind Escape key to cancel
        popup.bind('<Escape>', lambda e: cancel_scan())
        
        # Focus the notes field
        notes_entry.focus_set()

    def _load_product_records(self):
        records = []
        if self._logging_backend_uses_server_csv():
            records = self._load_server_product_records()
            if records and not self._logging_backend_uses_google():
                self.product_records = records
                self.product_options = [record["code"] for record in records]
                return records
        try:
            rows = product_sheet.get_all_values()[1:] if self._logging_backend_uses_google() else []
        except Exception:
            rows = []
            LOGGER.exception(structured_message("product_picker_load_failed"))

        for row in rows:
            code = str(row[PRODUCT_LOOKUP_COLUMNS["Product Code"]] if len(row) > PRODUCT_LOOKUP_COLUMNS["Product Code"] else "").strip()
            if not code:
                continue
            description = str(row[PRODUCT_LOOKUP_COLUMNS["Description"]] if len(row) > PRODUCT_LOOKUP_COLUMNS["Description"] else "").strip()
            expected_cycle = str(row[PRODUCT_LOOKUP_COLUMNS["Expected Cycle"]] if len(row) > PRODUCT_LOOKUP_COLUMNS["Expected Cycle"] else "").strip()
            barcode_display = str(row[PRODUCT_LOOKUP_COLUMNS["Barcode Display"]] if len(row) > PRODUCT_LOOKUP_COLUMNS["Barcode Display"] else "").strip()
            records.append(
                {
                    "code": code,
                    "description": description,
                    "barcode": barcode_display,
                    "expected_cycle": expected_cycle,
                    "search": f"{code} {description} {barcode_display}".lower(),
                }
            )

        if self._logging_backend_uses_server_csv():
            known_codes = {record["code"].strip().lower() for record in records}
            for server_record in self._load_server_product_records():
                if server_record["code"].strip().lower() not in known_codes:
                    records.append(server_record)
                    known_codes.add(server_record["code"].strip().lower())

        self.product_records = records
        self.product_options = [record["code"] for record in records]
        return records

    def _select_product(self, product_code, dialog=None):
        product_code = str(product_code or "").strip()
        if not product_code:
            return
        self.product_var.set(product_code)
        self.update_description_on_select(product_code)
        if dialog is not None:
            try:
                dialog.destroy()
            except Exception:
                pass
        try:
            self.barcode_entry.focus_set()
        except Exception:
            pass
        self._schedule_scan_focus()

    def open_product_picker(self):
        records = getattr(self, "product_records", None) or self._load_product_records()
        picker = ctk.CTkToplevel(self)
        picker.title("Product Selection")
        picker.geometry("1220x720")
        picker.minsize(1000, 620)
        picker.transient(self)
        picker.grab_set()
        picker.lift()
        picker.focus_force()

        def close_picker():
            try:
                picker.destroy()
            finally:
                self._schedule_scan_focus()

        header = ctk.CTkFrame(picker, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 6))
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(header, textvariable=search_var, placeholder_text="Search product", font=("Arial", 18), height=42)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(header, text="Close", width=120, height=42, command=close_picker).pack(side="right")

        count_var = ctk.StringVar(value="")
        ctk.CTkLabel(picker, textvariable=count_var, font=("Arial", 12), text_color="gray").pack(anchor="w", padx=16, pady=(0, 4))

        list_frame = ctk.CTkScrollableFrame(picker)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        picker_state = {"filtered": records}

        def render_products(*_):
            query = search_var.get().strip().lower()
            filtered = [record for record in records if not query or query in record["search"]]
            picker_state["filtered"] = filtered
            for child in list_frame.winfo_children():
                child.destroy()

            columns = 5
            for column in range(columns):
                list_frame.grid_columnconfigure(column, weight=1, uniform="product_col")

            for index, record in enumerate(filtered):
                row = index // columns
                column = index % columns
                button_text = record["code"]
                if record["description"]:
                    button_text = f"{button_text}\n{record['description'][:32]}"
                button = ctk.CTkButton(
                    list_frame,
                    text=button_text,
                    command=lambda code=record["code"]: self._select_product(code, picker),
                    height=58,
                    font=("Arial", 13, "bold"),
                    anchor="w",
                )
                button.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)

            count_var.set(f"{len(filtered)} product(s)")

        search_var.trace_add("write", render_products)
        picker.bind("<Escape>", lambda _event: close_picker())
        picker.protocol("WM_DELETE_WINDOW", close_picker)
        picker.bind(
            "<Return>",
            lambda _event: self._select_product(picker_state["filtered"][0]["code"], picker)
            if picker_state["filtered"]
            else None,
        )
        render_products()
        search_entry.focus_set()
        return picker

    def update_description_on_select(self, value=None):
        product_code = self.product_var.get()
        product_info = self.get_product_info_from_sources(product_code)
        description = product_info["description"] if product_info else "N/A"
        Barc = product_info["Barc"] if product_info else "N/A"
        PC = product_info["PC"] if product_info else "N/A"
        Expected_Cycle = product_info["Expected_Cycle"] if product_info else "N/A"
        parsed_cycle = parse_expected_cycle(Expected_Cycle)
        if parsed_cycle:
            self.expected_cycle = parsed_cycle
            self.expected_cycle_var.set(f"{parsed_cycle:.2f} sec")
        else:
            self.expected_cycle = 0.0
            self.expected_cycle_var.set("N/A")
        self.PC_var.set(PC)
        self.description_var.set(description)
        self.barcode_label_var.set(Barc)  # Set barcode label from Google Sheets
        # Don't set barcode_var here - it should remain empty for scanning

    
    def build_gui(self):
        compact = bool(getattr(self, "_main_ui_compact", False))
        outer_pad = 4 if compact else 10
        section_pady = 2 if compact else 5
        grid_pady = 1 if compact else 2
        kpi_font = self._main_font(82 if compact else 110, "bold")
        button_height = self._main_dim(30 if compact else 36, minimum=28)

        # Optional top logo (smaller for better space usage)
        try:
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
            if os.path.exists(logo_path) and not compact:
                img = Image.open(logo_path)
                # Reduced target height for better space usage
                target_h = self._main_dim(48, minimum=32)
                w, h = img.size
                if h > 0:
                    target_w = int(w * (target_h / float(h)))
                else:
                    target_w = target_h
                self._logo_img = img
                self._logo_ctkimg = ctk.CTkImage(light_image=img, dark_image=img, size=(target_w, target_h))
                logo_frame = ctk.CTkFrame(self)
                logo_frame.pack(pady=(outer_pad, section_pady), padx=outer_pad, fill="x")
                ctk.CTkLabel(logo_frame, image=self._logo_ctkimg, text="").pack(anchor="center")
        except Exception:
            pass

        # Centered title just below the logo
        title_bar = ctk.CTkFrame(self)
        title_bar.pack(pady=(0, section_pady if compact else 0), padx=outer_pad, fill="x")
        if compact:
            title_bar.grid_columnconfigure(0, weight=1)
            title_bar.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(title_bar, text="Production Dashboard", font=self._main_font(18, "bold")).grid(row=0, column=0, sticky="w", padx=5)
            ctk.CTkLabel(title_bar, textvariable=self.time_var, font=self._main_font(13)).grid(row=0, column=1, sticky="e", padx=5)
        else:
            ctk.CTkLabel(title_bar, text="Production Dashboard", font=self._main_font(24, "bold")).pack(anchor="center")

            # Time below title, centered
            time_bar = ctk.CTkFrame(self)
            time_bar.pack(pady=(0, section_pady), padx=outer_pad, fill="x")
            ctk.CTkLabel(time_bar, textvariable=self.time_var, font=self._main_font(18)).pack(anchor="center")

        # Production summary
        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(pady=section_pady, padx=outer_pad, fill="x")
        for column in range(4):
            info_frame.grid_columnconfigure(column, weight=1, uniform="summary_col")

        field_pad_x = self._main_dim(5, minimum=3)
        title_font = self._main_font(11 if compact else 12, "bold")
        value_font = self._main_font(15 if compact else 17, "bold")

        def add_summary_field(row, column, title, textvariable=None, value_text=None, columnspan=1, value_font_override=None, value_color=None):
            field = ctk.CTkFrame(info_frame, corner_radius=6)
            field.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=field_pad_x, pady=grid_pady)
            field.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                field,
                text=title.upper(),
                font=title_font,
                text_color="gray",
                anchor="w",
            ).grid(row=0, column=0, sticky="we", padx=10, pady=(6, 0))
            label_kwargs = {
                "font": value_font_override or value_font,
                "anchor": "w",
                "justify": "left",
            }
            if textvariable is not None:
                label_kwargs["textvariable"] = textvariable
                label_kwargs["text"] = ""
            else:
                label_kwargs["text"] = value_text or ""
            if value_color:
                label_kwargs["text_color"] = value_color
            value_label = ctk.CTkLabel(field, **label_kwargs)
            value_label.grid(row=1, column=0, sticky="we", padx=10, pady=(0, 8))
            return field, value_label

        self._load_product_records()
        product_field, product_placeholder = add_summary_field(0, 0, "Product", columnspan=1)
        product_placeholder.destroy()
        product_picker_frame = ctk.CTkFrame(product_field, fg_color="transparent")
        product_picker_frame.grid(row=1, column=0, sticky="we", padx=10, pady=(0, 8))
        product_picker_frame.grid_columnconfigure(0, weight=1)
        self.product_display_label = ctk.CTkLabel(
            product_picker_frame,
            textvariable=self.product_var,
            font=value_font,
            anchor="w",
        )
        self.product_display_label.grid(row=0, column=0, sticky="we", padx=(0, 6))
        ctk.CTkButton(
            product_picker_frame,
            text="Select",
            command=self.open_product_picker,
            width=self._main_dim(82, minimum=68),
            height=self._main_dim(28, minimum=24),
            font=self._main_font(12, "bold"),
        ).grid(row=0, column=1, sticky="e")

        add_summary_field(0, 1, "Description", self.description_var, columnspan=2, value_font_override=self._main_font(16 if compact else 18, "bold"))
        self.production_state_label = add_summary_field(0, 3, "Production", self.production_state_var, value_color="red")[1]
        add_summary_field(1, 0, "Barcode Label", self.barcode_label_var)
        add_summary_field(1, 1, "Last Scanned", self.last_scanned_var)
        _workcenter_field, self.workcenter_display = add_summary_field(1, 2, "Workcenter", value_text=self.current_workcenter)
        self.expected_cycle_label = add_summary_field(2, 0, "Expected Cycle", self.expected_cycle_var, columnspan=2)[1]
        self.cycle_label = add_summary_field(2, 2, "Current Cycle", self.cycle_time_var, columnspan=2, value_color="orange")[1]
        self.production_timer_label = add_summary_field(
            1,
            3,
            "Run Time",
            self.production_timer_var,
            columnspan=1,
            value_font_override=self._main_font(32 if compact else 42, "bold"),
            value_color="red",
        )[1]

        # Update scan entry state
        try:
            self._update_scan_entry_state()
        except Exception:
            pass
        self._refresh_health_display()

        # Production Count
        #ctk.CTkLabel(info_frame, text="Production Count:", font=("Arial", 18)).grid(row=2, column=0, sticky="e", padx=10, pady=8)
        #ctk.CTkLabel(info_frame, textvariable=self.production_count_var, font=("Arial", 18)).grid(row=2, column=1, sticky="w", padx=10, pady=5)

        # Production Runtime Timer
        #ctk.CTkLabel(info_frame, text="Production Time:", font=("Arial", 18)).grid(row=2, column=2, sticky="e", padx=10, pady=8)
        #self.production_timer_label = ctk.CTkLabel(info_frame, textvariable=self.production_timer_var, font=("Arial", 18), text_color="red")
        #self.production_timer_label.grid(row=2, column=3, sticky="w", padx=10, pady=5)

        # Description
        #ctk.CTkLabel(info_frame, text="Description:", font=("Arial", 18)).grid(row=1, column=0, sticky="e", padx=10, pady=8)
        #ctk.CTkLabel(info_frame, textvariable=self.description_var, font=("Arial", 18)).grid(row=1, column=1, sticky="w", padx=10, pady=5)

        # Barcode
        #ctk.CTkLabel(info_frame, text="Barcode:", font=("Arial", 18)).grid(row=1, column=4, sticky="e", padx=10, pady=8)
        #ctk.CTkLabel(info_frame, textvariable=self.barcode_var, font=("Arial", 18)).grid(row=1, column=5, sticky="w", padx=10, pady=5)

        # Barcode entry
        entry_frame = ctk.CTkFrame(self)
        entry_frame.pack(pady=section_pady, padx=outer_pad, fill="x")
        entry_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(entry_frame, text="Barcode:", font=self._main_font(14)).grid(row=0, column=0, sticky="e", padx=5, pady=grid_pady)
        self.barcode_entry = ctk.CTkEntry(entry_frame, textvariable=self.barcode_var, font=self._main_font(14), width=self._main_dim(300, minimum=220))
        self.barcode_entry.grid(row=0, column=1, sticky="we", padx=5, pady=grid_pady)
        # Remove the Enter key binding since we're handling it through the trace
        # self.barcode_entry.bind('<Return>', self.handle_scan)
        # Add trace to detect barcode scanner input
        self.barcode_var.trace_add('write', self._on_barcode_changed)
        self.enable_touch_keyboard(self.barcode_entry)
        self._install_scanner_capture()
        self.barcode_entry.focus_set()

        # Start/Stop buttons
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(pady=section_pady, padx=outer_pad, fill="x")
        
        # Configure grid columns with weights
        button_frame.grid_columnconfigure(0, weight=1, uniform="button_col")
        button_frame.grid_columnconfigure(1, weight=1, uniform="button_col")
        button_frame.grid_columnconfigure(2, weight=1, uniform="button_col")
        button_frame.grid_columnconfigure(3, weight=1, uniform="button_col")
        
        # Buttons with proportional width and reduced padding
        btn_style = {"width": self._main_dim(170, minimum=120), "height": button_height, "font": self._main_font(14, "bold")}
        ctk.CTkButton(button_frame, text="▶ Start", command=lambda: self.start_production(manual_start=True), 
                     fg_color="green", hover_color="dark green", **btn_style).grid(
                         row=0, column=0, padx=5, pady=grid_pady, sticky="nsew")
        ctk.CTkButton(button_frame, text="⏹ Stop", command=lambda: self.stop_production(manual_stop=True), 
                     fg_color="red", hover_color="dark red", **btn_style).grid(
                         row=0, column=1, padx=5, pady=grid_pady, sticky="nsew")
        ctk.CTkButton(button_frame, text="⚙ Setup", command=self.open_setup_popup, 
                     width=self._main_dim(120, minimum=90), height=button_height, font=self._main_font(14, "bold")).grid(
                         row=0, column=2, padx=5, pady=grid_pady, sticky="nsew")
        ctk.CTkButton(button_frame, text="Status & Logs", command=self.show_status_logs_dialog,
                     width=self._main_dim(150, minimum=110), height=button_height, font=self._main_font(14, "bold")).grid(
                         row=0, column=3, padx=5, pady=grid_pady, sticky="nsew")

        # KPI section in a grid (two columns)
        kpi_frame = ctk.CTkFrame(self)
        kpi_frame.pack(pady=section_pady, padx=outer_pad, fill="both", expand=True)
        kpi_frame.grid_columnconfigure(0, weight=1)
        kpi_frame.grid_columnconfigure(1, weight=1)
        
        # Production Count KPI
        kpi_left = ctk.CTkFrame(kpi_frame, corner_radius=10)
        kpi_left.grid(row=0, column=0, sticky="nsew", padx=5, pady=section_pady)
        kpi_left.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(kpi_left, text="Production Count", font=self._main_font(14 if compact else 16, "bold"), text_color="lime").pack(pady=(section_pady, 1))
        self.big_prod_count_label = ctk.CTkLabel(
            kpi_left, 
            textvariable=self.production_count_var, 
            font=kpi_font,
            text_color="lime"
        )
        self.big_prod_count_label.pack(expand=True, fill="both")
        
        # PCS/min KPI
        kpi_right = ctk.CTkFrame(kpi_frame, corner_radius=10)
        kpi_right.grid(row=0, column=1, sticky="nsew", padx=5, pady=section_pady)
        kpi_right.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(kpi_right, text="PCS/min", font=self._main_font(14 if compact else 16, "bold"), text_color="cyan").pack(pady=(section_pady, 1))
        self.big_pcs_min_label = ctk.CTkLabel(
            kpi_right, 
            textvariable=self.pcs_min_var, 
            font=kpi_font,
            text_color="cyan"
        )
        self.big_pcs_min_label.pack(expand=True, fill="both")

        # ZPL Presets (selection + Preview/Test Print)
        zpl_frame = ctk.CTkFrame(self, height=self._main_dim(42, minimum=34))
        zpl_frame.pack(pady=section_pady, padx=outer_pad, fill="x")
        
        # Configure grid for ZPL controls
        zpl_frame.grid_columnconfigure(0, weight=1)
        zpl_frame.grid_columnconfigure(1, minsize=self._main_dim(40, minimum=30))
        zpl_frame.grid_columnconfigure(2, minsize=self._main_dim(100, minimum=76))
        zpl_frame.grid_columnconfigure(3, minsize=self._main_dim(160, minimum=116))
        
        # Dropdown for ZPL presets
        self.zpl_preset = ctk.StringVar()
        self.zpl_dropdown = ctk.CTkComboBox(
            zpl_frame,
            variable=self.zpl_preset,
            values=self.load_zpl_preset_names(),
            width=self._main_dim(200, minimum=150),
            state="readonly",
            font=self._main_font(12),
            command=self._on_zpl_preset_changed,
            dropdown_font=self._main_font(12)
        )
        self.zpl_dropdown.grid(row=0, column=0, padx=2, pady=section_pady, sticky="we")
        self.enable_touch_keyboard(self.zpl_dropdown)

        # Refresh button
        ctk.CTkButton(zpl_frame, text="↻", width=self._main_dim(30, minimum=26), height=self._main_dim(30, minimum=26), 
                     command=self.refresh_zpl_presets).grid(
                         row=0, column=1, padx=2, pady=section_pady, sticky="w")
        
        # Browse button
        ctk.CTkButton(zpl_frame, text="Browse...", width=self._main_dim(90, minimum=74), height=self._main_dim(30, minimum=26),
                     command=self._browse_zpl_presets_dir).grid(
                         row=0, column=2, padx=2, pady=section_pady, sticky="w")
        
        # Preview/Test Print button
        ctk.CTkButton(zpl_frame, text="Preview / Test", width=self._main_dim(150, minimum=112), height=self._main_dim(30, minimum=26),
                     command=self.preview_zpl).grid(
                         row=0, column=3, padx=2, pady=section_pady, sticky="w")

        # Initial selection: saved preset or first
        _presets = self.load_zpl_preset_names()
        if hasattr(self, "_saved_zpl_preset") and self._saved_zpl_preset in _presets:
            self.zpl_dropdown.set(self._saved_zpl_preset)
        elif _presets:
            self.zpl_dropdown.set(_presets[0])
        self._on_zpl_preset_changed(self.zpl_dropdown.get() if hasattr(self, 'zpl_dropdown') else None)
        try:
            self._save_user_prefs()
        except Exception:
            pass

        self._install_scanner_capture()

        # (Statuses panel moved to Setup)

    def load_zpl_preset_names(self):
        """Load just the filenames of available ZPL presets"""
        presets = []
        # First check custom directory if set
        if hasattr(self, 'custom_zpl_presets_dir') and self.custom_zpl_presets_dir:
            try:
                if os.path.exists(self.custom_zpl_presets_dir):
                    presets.extend([f for f in os.listdir(self.custom_zpl_presets_dir) 
                                 if f.lower().endswith('.zpl')])
            except Exception as e:
                print(f"Error reading custom ZPL directory: {e}")
        
        # Then check default directory
        try:
            if os.path.exists(ZPL_PRESETS_DIR):
                default_presets = [f for f in os.listdir(ZPL_PRESETS_DIR) 
                                if f.lower().endswith('.zpl') and f not in presets]
                presets.extend(default_presets)
        except Exception as e:
            print(f"Error reading default ZPL directory: {e}")
                
        return presets

    def refresh_zpl_presets(self):
        current_selection = self.zpl_dropdown.get() if hasattr(self, 'zpl_dropdown') else ''
        presets = self.load_zpl_preset_names()
        try:
            self.zpl_dropdown.configure(values=presets)
            if current_selection in presets:
                self.zpl_dropdown.set(current_selection)
            elif presets:
                self.zpl_dropdown.set(presets[0])
            self._save_user_prefs()
        except Exception:
            pass

    def _browse_zpl_presets_dir(self):
        """Open a directory dialog to select ZPL presets directory"""
        dir_path = filedialog.askdirectory(
            title="Select ZPL Presets Directory",
            mustexist=True
        )
        
        if dir_path:
            self.custom_zpl_presets_dir = dir_path
            # Save the custom directory to user prefs
            self._save_user_prefs()
            # Refresh the presets list
            self.refresh_zpl_presets()
            messagebox.showinfo(
                "Success", 
                f"ZPL presets directory set to:\n{dir_path}"
            )
    
    def get_zpl_template(self):
        """Get the content of the selected ZPL template"""
        try:
            selected_preset = self.zpl_preset.get() if hasattr(self, 'zpl_preset') else ''
            if not selected_preset:
                return ""
                
            # First check custom directory if set
            if hasattr(self, 'custom_zpl_presets_dir') and self.custom_zpl_presets_dir:
                custom_path = os.path.join(self.custom_zpl_presets_dir, selected_preset)
                if os.path.exists(custom_path):
                    with open(custom_path, 'r', encoding='utf-8') as f:
                        return f.read()
            
            # Then check default directory
            default_path = os.path.join(ZPL_PRESETS_DIR, selected_preset)
            if os.path.exists(default_path):
                with open(default_path, 'r', encoding='utf-8') as f:
                    return f.read()
                    
        except Exception as e:
            print(f"Error loading ZPL template: {e}")
            
        return ""

    def preview_zpl(self):
        try:
            zpl_template = self.get_zpl_template()
            if not zpl_template:
                messagebox.showwarning("No Template", "No ZPL template selected or template is empty.")
                return
            preview_window = ctk.CTkToplevel(self)
            preview_window.title("ZPL Preview")
            preview_window.geometry("600x400")
            try:
                preview_window.attributes('-topmost', True)
            except Exception:
                pass
            preview_window.lift(); preview_window.focus_force(); preview_window.grab_set()
            preview_frame = ctk.CTkFrame(preview_window)
            preview_frame.pack(expand=True, fill="both", padx=10, pady=10)
            ctk.CTkLabel(preview_frame, text="ZPL Code Preview\n(Simulated - actual print may vary)", font=("Arial", 12, "bold")).pack(pady=10)
            zpl_text = ctk.CTkTextbox(preview_frame, width=580, height=300)
            zpl_text.insert("1.0", zpl_template)
            self.enable_touch_keyboard(zpl_text)  # Enable touch keyboard for ZPL preview
            zpl_text.configure(state="disabled")
            zpl_text.pack(pady=10, padx=10, fill="both", expand=True)
            ctk.CTkButton(preview_frame, text="Print Test Label", command=lambda: self.print_preview(zpl_template)).pack(pady=10)
            def _on_close():
                try:
                    preview_window.grab_release(); preview_window.attributes('-topmost', False)
                except Exception:
                    pass
                preview_window.destroy()
            preview_window.protocol("WM_DELETE_WINDOW", _on_close)
        except Exception as e:
            messagebox.showerror("Preview Error", f"Error generating preview: {str(e)}")
            LOGGER.exception(structured_message("printer_preview_window_failed"))

    def print_preview(self, zpl_code):
        try:
            printer_name = win32print.GetDefaultPrinter()
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                job = win32print.StartDocPrinter(hprinter, 1, ("ZPL Preview", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hprinter)
                    win32print.WritePrinter(hprinter, zpl_code.encode('utf-8'))
                    win32print.EndPagePrinter(hprinter)
                finally:
                    win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
            messagebox.showinfo("Print Started", "ZPL preview sent to printer.")
        except Exception as e:
            messagebox.showerror("Print Error", f"Error sending to printer: {str(e)}")

    def _on_toggle_teraoka(self):
        try:
            if self.teraoka_enabled.get():
                # Turning ON: start client
                if not self.teraoka:
                    try:
                        teraoka_client_class = load_teraoka_client()
                        self.teraoka = start_teraoka_client(
                            teraoka_client_class,
                            self.teraoka_wsdl,
                            self.current_workcenter,
                            self.teraoka_supervisor,
                        )
                        try:
                            self.teraoka.enqueue_receipt(0)
                        except Exception:
                            LOGGER.exception(structured_message("teraoka_enqueue_failed_on_toggle", workcenter=self.current_workcenter))
                    except Exception:
                        self.teraoka = None
                        LOGGER.exception(structured_message("teraoka_start_failed_on_toggle", workcenter=self.current_workcenter))
                self.teraoka_status_var.set("Teraoka: CONNECTING...")
                self._set_health_signal("teraoka", HEALTH_WARNING, "Connecting")
            else:
                # Turning OFF: shutdown client, set status
                try:
                    shutdown_teraoka_client(self.teraoka)
                except Exception:
                    LOGGER.exception(structured_message("teraoka_shutdown_failed_on_toggle", workcenter=self.current_workcenter))
                self.teraoka = None
                self.teraoka_status_var.set("Teraoka: DISABLED")
                self.teraoka_job_var.set("Job: -")
                self._set_health_signal("teraoka", HEALTH_UNKNOWN, "Disabled")
            self._apply_status_colors()
        except Exception:
            LOGGER.exception(structured_message("teraoka_toggle_failed", workcenter=self.current_workcenter))
            self._set_health_signal("teraoka", HEALTH_ERROR, "Toggle failed")
        finally:
            try:
                self._update_scan_entry_state()
            except Exception:
                pass

    def _update_scan_entry_state(self):
        """Enable/disable the scan entry based on Teraoka toggle and readiness."""
        try:
            if not hasattr(self, 'barcode_entry') or self.barcode_entry is None:
                return
            # If Teraoka is disabled, allow scanning freely
            if not self.teraoka_enabled.get():
                self.barcode_entry.configure(state="normal")
                self._schedule_scan_focus()
                return
            # Teraoka enabled: require connected AND job available
            connected = False
            job_ok = False
            try:
                if getattr(self, 'teraoka', None):
                    connected = bool(self.teraoka.is_connected())
                    job_ok = bool(self.teraoka.current_job())
            except Exception:
                connected = False
                job_ok = False
            ready = connected and job_ok
            self.barcode_entry.configure(state=("normal" if ready else "disabled"))
            if ready:
                self._schedule_scan_focus()
        except Exception:
            pass

    # ------------------- AUTO DOWNTIME CHECK -------------------
    def check_auto_downtime(self):
        if self.production_running and self.expected_cycle > 0:
            now = datetime.now()
            active_break = self._get_active_planned_break_window(now)
            active_context = getattr(self, "_active_planned_break_context", None)

            if active_break:
                # Scheduled Tea/Lunch breaks are logger-authored downtime events.
                # Suppress the normal unplanned auto-detect path inside those
                # windows so the dashboard does not see compounded break rows.
                if not isinstance(self.last_scan_time, datetime):
                    self.after(1000, self.check_auto_downtime)
                    return
                saw_scan_during_break = (
                    isinstance(self.last_scan_time, datetime)
                    and active_break["start"] <= self.last_scan_time < active_break["end"]
                )
                if not active_context or active_context.get("key") != active_break["key"]:
                    active_break["saw_scan_during_break"] = saw_scan_during_break
                    self._active_planned_break_context = active_break
                    log_event(
                        LOGGER,
                        logging.INFO,
                        "planned_break_window_active",
                        reason=active_break["label"],
                        workcenter=active_break["workcenter"],
                        start_at=format_contract_timestamp(active_break["start"]),
                        end_at=format_contract_timestamp(active_break["end"]),
                    )
                else:
                    active_context["saw_scan_during_break"] = bool(active_context.get("saw_scan_during_break")) or saw_scan_during_break
                self.after(1000, self.check_auto_downtime)
                return

            if active_context:
                self._finalize_planned_break_context(now)

            if self.last_scan_time:
                delay = (now - self.last_scan_time).total_seconds()
                if delay > self._get_auto_downtime_multiplier() * self.expected_cycle and not self.in_auto_downtime:
                    self.in_auto_downtime = True
                    downtime_reason = "Auto Detected"
                    stop_start = self.last_scan_time if isinstance(self.last_scan_time, datetime) else now
                    self.start_downtime_popup(downtime_reason, delay=delay, stop_start=stop_start)
        else:
            self._active_planned_break_context = None
        self.after(1000, self.check_auto_downtime)  # check every second
    def get_downtime_periods(self):
        """
        Returns a list of (start_datetime, end_datetime, reason) tuples for all logged downtimes.
        """
        periods = []
        try:
            rows = downtime_sheet.get_all_values()[1:]  # skip header if present
            for row in rows:
                if len(row) >= 3:
                    start_str, duration_str, reason = row[:3]
                    try:
                        start = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                        duration = float(duration_str)
                        end = start + timedelta(seconds=duration)
                        periods.append((start, end, reason))
                    except Exception:
                        continue
        except Exception:
            pass
        return periods


        # Update cycle time label if available
        for row in product_sheet.get_all_values()[1:]:
            if row[0] == product_code and len(row) > 4:
                self.cycle_label.configure(text=f"{row[4]} sec")
                break

    def update_time(self):
        now = datetime.now()
        
        self.time_var.set(now.strftime("%H:%M:%S"))
        if self.production_running and self.start_time:
            runtime = now - self.start_time
            self.runtime_var.set(str(runtime).split('.')[0])
        self.after(1000, self.update_time)

    def start_production(self, manual_start=True):
        try:
            print(f"[DEBUG] start_production called with manual_start={manual_start}")
            
            if manual_start and (self.auto_prod_enabled.get() or self.overtime_enabled.get()):
                print(f"[INFO] Manual start blocked - auto production is enabled")
                messagebox.showinfo("Auto Production", "Production is controlled automatically based on the schedule")
                return
                
            if not self.product_var.get():
                print(f"[ERROR] No product selected - cannot start production")
                messagebox.showerror("Error", "Please select a product before starting production.")
                return
                
            print(f"[DEBUG] Product selected: {self.product_var.get()}")
            product_info = self.get_product_info_from_sources(self.product_var.get())
            raw_expected_cycle = product_info.get("Expected_Cycle", "") if product_info else ""
            parsed_cycle = parse_expected_cycle(raw_expected_cycle)
            if parsed_cycle:
                self.expected_cycle = parsed_cycle
                self.expected_cycle_var.set(f"{parsed_cycle:.2f} sec")
                print(f"[DEBUG] Set expected cycle to {parsed_cycle} seconds")
            else:
                self.expected_cycle = 0.0
                self.expected_cycle_var.set("N/A")
                print("[DEBUG] No valid cycle time found")
            if product_info:
                self.description_var.set(product_info.get("description", "") or "N/A")
                self.PC_var.set(product_info.get("PC", "") or "N/A")
                self.barcode_label_var.set(product_info.get("Barc", "") or "N/A")

            proposed_start_time = datetime.now()
            start_row = build_production_event_row(
                timestamp=proposed_start_time,
                event_type=PRODUCTION_EVENT_START,
                product_code=self.product_var.get() or 'N/A',
                duration_seconds=0.0,
                production_count=0,
                operator=self.operator_name_var.get() or 'Unknown',
                workcenter=self.current_workcenter,
            )
            try:
                start_event_id = self._commit_local_production_event(start_row)
            except Exception as e:
                LOGGER.exception(
                    structured_message(
                        "production_start_local_commit_failed",
                        product_code=self.product_var.get(),
                        workcenter=self.current_workcenter,
                        manual_start=manual_start,
                        db_path=self.local_db_file,
                    )
                )
                self._set_health_signal("local_store", HEALTH_ERROR, "Production start commit failed")
                messagebox.showerror("Storage Error", "Failed to store the production start locally. Production was not started.")
                return

            self.start_time = proposed_start_time
            self.production_count = 0
            self.production_count_var.set("0")
            self.total_runtime_seconds = 0
            self.last_update_time = datetime.now()
            self.in_auto_downtime = False
            self.production_timer_var.set("00:00:00")
            self.production_running = True
            self._clear_barcode_entry()
            self.last_scan_time = None
            try:
                self._update_scan_entry_state()
            except Exception:
                pass
            self._schedule_scan_focus(force=True, attempts=4)
            
            print(f"[INFO] Production started at {self.start_time}")
            log_event(
                LOGGER,
                logging.INFO,
                "production_started",
                product_code=self.product_var.get(),
                workcenter=self.current_workcenter,
                manual_start=manual_start,
            )
            
            try:
                self.production_timer_label.configure(text_color="green")
                print(f"[DEBUG] Updated timer label color to green")
            except Exception as e:
                print(f"[WARNING] Failed to update timer label color: {e}")
                
            try:
                self.production_state_var.set("RUNNING")
                self._apply_status_colors()
                print(f"[DEBUG] Updated production state to RUNNING")
            except Exception as e:
                print(f"[WARNING] Failed to update production state: {e}")
            try:
                threading.Thread(
                    target=self._async_sync_production_event,
                    args=(start_event_id,),
                    daemon=True,
                ).start()
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "production_start_sync_worker_failed",
                        event_id=start_event_id,
                        workcenter=self.current_workcenter,
                    )
                )
                self._set_health_signal("excel", HEALTH_WARNING, "Production start stored locally; export worker failed")
                self._set_health_signal("google_write", HEALTH_WARNING, "Production start stored locally; sync worker failed")
            
        except Exception as e:
            print(f"[ERROR] Critical error in start_production: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            LOGGER.exception(
                structured_message(
                    "production_start_failed",
                    product_code=self.product_var.get(),
                    workcenter=self.current_workcenter,
                    manual_start=manual_start,
                )
            )
            messagebox.showerror("Start Production Error", str(e))

    def stop_production(self, manual_stop=True):
        try:
            print(f"[DEBUG] stop_production called with manual_stop={manual_stop}")
            
            if manual_stop and (self.auto_prod_enabled.get() or self.overtime_enabled.get()):
                print(f"[INFO] Manual stop blocked - auto production is enabled")
                messagebox.showinfo("Auto Production", "Production is controlled automatically based on the schedule")
                return
                
            if not hasattr(self, 'start_time') or not self.start_time:
                print(f"[WARNING] Production was not started properly")
                messagebox.showwarning("Warning", "Production was not started properly")
                return
                
            print(f"[DEBUG] Stopping production...")
            end_time = datetime.now()
            duration = calculate_production_duration(self.start_time, end_time)
            print(f"[DEBUG] Production duration: {duration:.2f} seconds")

            stop_row = build_production_event_row(
                timestamp=end_time,
                event_type=PRODUCTION_EVENT_END,
                product_code=self.product_var.get() or 'N/A',
                duration_seconds=duration,
                production_count=self.production_count,
                operator=self.operator_name_var.get() or 'Unknown',
                workcenter=self.current_workcenter,
            )
            try:
                stop_event_id = self._commit_local_production_event(stop_row)
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "production_stop_local_commit_failed",
                        product_code=self.product_var.get(),
                        workcenter=self.current_workcenter,
                        manual_stop=manual_stop,
                        duration_seconds=f"{duration:.2f}",
                        db_path=self.local_db_file,
                    )
                )
                self._set_health_signal("local_store", HEALTH_ERROR, "Production stop commit failed")
                messagebox.showerror("Storage Error", "Failed to store the production stop locally. Production is still running.")
                return

            self.production_running = False
            self._clear_barcode_entry()

            try:
                self.production_timer_label.configure(text_color="red")
                print(f"[DEBUG] Updated timer label color to red")
            except Exception as e:
                print(f"[WARNING] Failed to update timer label color: {e}")
            
            try:
                self.production_state_var.set("STOPPED")
                self._apply_status_colors()
                print(f"[DEBUG] Updated production state to STOPPED")
            except Exception as e:
                print(f"[WARNING] Failed to update production state: {e}")
            try:
                threading.Thread(
                    target=self._async_sync_production_event,
                    args=(stop_event_id,),
                    daemon=True,
                ).start()
            except Exception:
                LOGGER.exception(
                    structured_message(
                        "production_stop_sync_worker_failed",
                        event_id=stop_event_id,
                        workcenter=self.current_workcenter,
                    )
                )
                self._set_health_signal("excel", HEALTH_WARNING, "Production stop stored locally; export worker failed")
                self._set_health_signal("google_write", HEALTH_WARNING, "Production stop stored locally; sync worker failed")
            
            # Reset production count for next session
            self.production_count = 0
            self.production_count_var.set("0")
            print(f"[DEBUG] Reset production count to 0")
            print(f"[INFO] Production stopped at {end_time}")
            log_event(
                LOGGER,
                logging.INFO,
                "production_stopped",
                product_code=self.product_var.get(),
                workcenter=self.current_workcenter,
                manual_stop=manual_stop,
                duration_seconds=f"{duration:.2f}",
            )
            
        except Exception as e:
            print(f"[ERROR] Critical error in stop_production: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            LOGGER.exception(
                structured_message(
                    "production_stop_failed",
                    product_code=self.product_var.get(),
                    workcenter=self.current_workcenter,
                    manual_stop=manual_stop,
                )
            )
            messagebox.showerror("Stop Production Error", str(e))

    def update_production_timer(self):
        now = datetime.now()

        if self.production_running and not self.in_auto_downtime:
            if self.last_update_time:
                self.total_runtime_seconds += (now - self.last_update_time).total_seconds()

            self.production_timer_var.set(str(timedelta(seconds=int(self.total_runtime_seconds))))
            try:
                self.production_timer_label.configure(text_color="green")
            except Exception:
                pass
        else:
            try:
                self.production_timer_label.configure(text_color="red")
            except Exception:
                pass

        self.last_update_time = now
        try:
            self._apply_status_colors()
        except Exception:
            pass
        self.after(1000, self.update_production_timer)  # refresh every second

    def check_production_schedule(self):
        """Check if production should be started or stopped based on schedule."""
        self._production_schedule_after_id = None
        if getattr(self, "_shutdown_requested", False):
            return
        print(f"[DEBUG] Schedule checker method called")
        try:
            current_time = datetime.now().time()
            print(f"[DEBUG] ========== Production schedule check at {current_time} ==========")
            print(f"[DEBUG] Auto production enabled: {self.auto_prod_enabled.get()}")
            print(f"[DEBUG] Overtime enabled: {self.overtime_enabled.get()}")
            print(f"[DEBUG] Production running: {self.production_running}")
            print(f"[DEBUG] Product selected: {self.product_var.get()}")
            print(f"[DEBUG] Auto start time: {self.auto_start_time.get()}")
            print(f"[DEBUG] Auto stop time: {self.auto_stop_time.get()}")
            print(f"[DEBUG] Overtime start time: {self.overtime_start_time.get()}")
            print(f"[DEBUG] Overtime stop time: {self.overtime_stop_time.get()}")
            
            # Check if auto production is actually enabled
            if not self.auto_prod_enabled.get() and not self.overtime_enabled.get():
                print(f"[DEBUG] Neither auto production nor overtime is enabled - skipping check")
                return
            
            def parse_time(time_str):
                try:
                    print(f"[DEBUG] Parsing time: {time_str}")
                    h, m = map(int, time_str.split(':'))
                    # Create a time object using a datetime instance
                    parsed_time = datetime(2000, 1, 1, h, m).time()
                    print(f"[DEBUG] Parsed time: {parsed_time}")
                    return parsed_time
                except Exception as e:
                    print(f"[ERROR] Failed to parse time '{time_str}': {e}")
                    return None
                    
            # Check regular production hours
            if self.auto_prod_enabled.get():
                print(f"[DEBUG] Checking regular production hours")
                start_time = parse_time(self.auto_start_time.get())
                stop_time = parse_time(self.auto_stop_time.get())
                
                if start_time and stop_time:
                    print(f"[DEBUG] Regular production window: {start_time} - {stop_time}")
                    print(f"[DEBUG] Current time: {current_time}")
                    
                    if start_time <= current_time <= stop_time:
                        if not self.production_running:
                            # Check if a product is selected before starting
                            if self.product_var.get():
                                print(f"[INFO] Auto-starting production at {current_time}")
                                try:
                                    self.start_production(manual_start=False)
                                    print(f"[INFO] Production started successfully")
                                except Exception as e:
                                    print(f"[ERROR] Failed to start production: {e}")
                            else:
                                print(f"[WARNING] Auto-production time reached but no product selected")
                        else:
                            print(f"[DEBUG] Production already running within regular hours")
                        return
                    elif self.production_running:
                        # Check if we're in overtime window
                        in_overtime = False
                        if self.overtime_enabled.get():
                            ot_start = parse_time(self.overtime_start_time.get())
                            ot_stop = parse_time(self.overtime_stop_time.get())
                            if ot_start and ot_stop and ot_start <= current_time <= ot_stop:
                                in_overtime = True
                                print(f"[DEBUG] Production continuing in overtime window")
                        
                        if not in_overtime:
                            print(f"[INFO] Auto-stopping production at {current_time} (outside all production hours)")
                            try:
                                self.stop_production(manual_stop=False)
                                print(f"[INFO] Production stopped successfully")
                            except Exception as e:
                                print(f"[ERROR] Failed to stop production: {e}")
                            return
                        else:
                            print(f"[DEBUG] Production continuing - current time in overtime window")
                else:
                    print(f"[ERROR] Invalid time configuration for regular production")
                        
            # Check overtime hours
            if self.overtime_enabled.get():
                print(f"[DEBUG] Checking overtime hours")
                ot_start = parse_time(self.overtime_start_time.get())
                ot_stop = parse_time(self.overtime_stop_time.get())
                
                if ot_start and ot_stop:
                    print(f"[DEBUG] Overtime window: {ot_start} - {ot_stop}")
                    print(f"[DEBUG] Current time: {current_time}")
                    
                    if ot_start <= current_time <= ot_stop:
                        if not self.production_running:
                            # Check if a product is selected before starting
                            if self.product_var.get():
                                print(f"[INFO] Auto-starting overtime production at {current_time}")
                                try:
                                    self.start_production(manual_start=False)
                                    print(f"[INFO] Overtime production started successfully")
                                except Exception as e:
                                    print(f"[ERROR] Failed to start overtime production: {e}")
                            else:
                                print(f"[WARNING] Auto-overtime time reached but no product selected")
                        else:
                            print(f"[DEBUG] Production already running")
                        return
                    elif self.production_running and current_time > ot_stop:
                        print(f"[INFO] Auto-stopping overtime production at {current_time}")
                        try:
                            self.stop_production(manual_stop=False)
                            print(f"[INFO] Overtime production stopped successfully")
                        except Exception as e:
                            print(f"[ERROR] Failed to stop overtime production: {e}")
                        return
                else:
                    print(f"[ERROR] Invalid time configuration for overtime")
                        
            # If we're outside any valid production time and auto mode is on, stop production
            if (self.auto_prod_enabled.get() or self.overtime_enabled.get()) and self.production_running:
                print(f"[INFO] Auto-stopping production (outside all schedules) at {current_time}")
                try:
                    self.stop_production(manual_stop=False)
                    print(f"[INFO] Production stopped successfully")
                except Exception as e:
                    print(f"[ERROR] Failed to stop production: {e}")
            else:
                print(f"[DEBUG] No action needed - production conditions not met")
                
        except Exception as e:
            print(f"[ERROR] Critical error in production schedule: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            LOGGER.exception(structured_message("production_schedule_check_failed"))
        finally:
            if not getattr(self, "_shutdown_requested", False):
                print(f"[DEBUG] Scheduling next check in 60 seconds")
                self._schedule_next_production_check(60000)

    def open_setup_popup(self):
        pw_popup = ctk.CTkToplevel(self)
        pw_popup.title("Password Required")
        pw_popup.geometry("400x200")

        ctk.CTkLabel(pw_popup, text="Enter Password:", font=("Arial", 18)).pack(pady=20)
        pw_var = ctk.StringVar()
        pw_entry = ctk.CTkEntry(pw_popup, textvariable=pw_var, font=("Arial", 18), show="*")
        pw_entry.pack(pady=10)
        self.enable_touch_keyboard(pw_entry)  # Enable touch keyboard for password entry

        def check_pw():
            if pw_var.get() == "2435":
                pw_popup.destroy()
                self.show_setup_popup()
            else:
                messagebox.showerror("Access Denied", "Incorrect password.", parent=pw_popup)

        ctk.CTkButton(pw_popup, text="Submit", command=check_pw).pack(pady=10)
        pw_popup.bind("<Return>", lambda _event: check_pw())
        self._present_app_dialog(pw_popup, focus_widget=pw_entry)

    def show_setup_popup(self):
        setup_popup = ctk.CTkToplevel(self)
        setup_popup.title("Setup")
        setup_popup.geometry("1000x700")  # Adjusted size for better fit on 1280x800 screens
        setup_popup.minsize(900, 600)  # Set minimum size to prevent it from being too small
        
        # Center the window
        setup_popup.update_idletasks()
        width = 1000
        height = 700
        x = (setup_popup.winfo_screenwidth() // 2) - (width // 2)
        y = (setup_popup.winfo_screenheight() // 2) - (height // 2)
        setup_popup.geometry(f'1000x700+{x}+{y}')
        self._present_app_dialog(setup_popup)
        # Create a scrollable frame for the setup content
        scrollable_frame = ctk.CTkScrollableFrame(setup_popup)
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)  # Reduced padding

        # Container
        container = ctk.CTkFrame(scrollable_frame)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        # Edit ZPL Section
        zpl_section = ctk.CTkFrame(container)
        zpl_section.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(zpl_section, text="Edit ZPL", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        # Show which preset is being edited
        current_preset = None
        try:
            current_preset = self.zpl_preset.get() if hasattr(self, 'zpl_preset') else None
        except Exception:
            current_preset = None
        presets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zpl_presets")
        os.makedirs(presets_dir, exist_ok=True)
        # Fallback to first available preset if none selected
        if not current_preset:
            names = self.load_zpl_preset_names()
            if names:
                current_preset = names[0]
        current_preset_path = self._resolve_zpl_preset_path(current_preset)
        if current_preset and not current_preset_path:
            current_preset_path = os.path.join(presets_dir, current_preset)
        ctk.CTkLabel(zpl_section, text=f"Editing: {current_preset or 'No preset selected'}", font=("Arial", 12)).pack(anchor="w", padx=10)
        zpl_text = ctk.CTkTextbox(zpl_section, font=("Consolas", 12), width=800, height=200)
        self.enable_touch_keyboard(zpl_text)  # Enable touch keyboard for ZPL editor
        zpl_text.pack(padx=10, pady=(0,10), fill="x")
        self.setup_zpl_text_widget = zpl_text
        try:
            if current_preset_path:
                if os.path.exists(current_preset_path):
                    with open(current_preset_path, 'r', encoding='utf-8') as f:
                        zpl_text.insert("1.0", f.read())
                else:
                    zpl_text.insert("1.0", "")
            else:
                zpl_text.insert("1.0", "")
        except Exception:
            zpl_text.insert("1.0", "")

        # Label size for the active preset
        label_section = ctk.CTkFrame(container)
        label_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(label_section, text="Label Size", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        current_dimensions = self._extract_zpl_dimensions_mm(
            current_preset or "",
            zpl_text.get("1.0", "end-1c"),
        ) or (LABEL_WIDTH, LABEL_HEIGHT)
        self.setup_label_width_var = ctk.StringVar(value=self._format_label_dimension(current_dimensions[0]))
        self.setup_label_height_var = ctk.StringVar(value=self._format_label_dimension(current_dimensions[1]))
        label_fields = ctk.CTkFrame(label_section, fg_color="transparent")
        label_fields.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(label_fields, text="Width (mm):", font=("Arial", 14)).pack(side="left", padx=(0, 8))
        width_entry = ctk.CTkEntry(label_fields, textvariable=self.setup_label_width_var, width=110, font=("Arial", 14))
        width_entry.pack(side="left", padx=(0, 16))
        self.enable_touch_keyboard(width_entry)
        ctk.CTkLabel(label_fields, text="Height (mm):", font=("Arial", 14)).pack(side="left", padx=(0, 8))
        height_entry = ctk.CTkEntry(label_fields, textvariable=self.setup_label_height_var, width=110, font=("Arial", 14))
        height_entry.pack(side="left")
        self.enable_touch_keyboard(height_entry)
        ctk.CTkLabel(
            label_section,
            text="Saved with the selected preset and also kept as the fallback label size.",
            font=("Arial", 12),
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # Workcenter Section
        wc_section = ctk.CTkFrame(container)
        wc_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(wc_section, text="Workcenter", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        wc_values = [wc.get("id") for wc in self.workcenters]
        wc_var = ctk.StringVar(value=self.current_workcenter)
        def _on_wc_change(v):
            try:
                # This will show the password dialog and only update if password is correct
                self._on_workcenter_selected(v)
            except Exception as e:
                print(f"Error changing workcenter: {e}")
                # Revert to the current workcenter in the UI if there's an error
                wc_var.set(self.current_workcenter)
        wc_menu = ctk.CTkOptionMenu(wc_section, values=wc_values, variable=wc_var, command=_on_wc_change)
        wc_menu.pack(padx=10, pady=(0,10), anchor="w")

        # Data logging backend
        logging_section = ctk.CTkFrame(container)
        logging_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(logging_section, text="Data Logging", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        self.setup_logging_backend_var = ctk.StringVar(value=getattr(self, "logging_backend", LOG_BACKEND_GOOGLE))
        self.setup_server_csv_dir_var = ctk.StringVar(value=getattr(self, "server_csv_dir", ""))

        backend_frame = ctk.CTkFrame(logging_section, fg_color="transparent")
        backend_frame.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(backend_frame, text="Write/read using:", font=("Arial", 12)).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(
            backend_frame,
            values=LOG_BACKEND_OPTIONS,
            variable=self.setup_logging_backend_var,
            width=180,
        ).pack(side="left", padx=(0, 12))

        path_frame = ctk.CTkFrame(logging_section, fg_color="transparent")
        path_frame.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(path_frame, text="Server CSV directory:", font=("Arial", 12)).pack(side="left", padx=(0, 8))
        server_entry = ctk.CTkEntry(path_frame, textvariable=self.setup_server_csv_dir_var, width=560, font=("Arial", 12))
        server_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.enable_touch_keyboard(server_entry)

        def browse_server_csv_dir():
            selected = filedialog.askdirectory(title="Select Server CSV Directory", parent=setup_popup)
            if selected:
                self.setup_server_csv_dir_var.set(selected)

        def initialise_setup_server_csv_dir():
            previous_dir = getattr(self, "server_csv_dir", "")
            self.server_csv_dir = self.setup_server_csv_dir_var.get().strip()
            try:
                self.test_server_csv_directory(show_dialog=True)
            finally:
                self.server_csv_dir = previous_dir

        ctk.CTkButton(path_frame, text="Browse", width=90, command=browse_server_csv_dir).pack(side="left", padx=(0, 8))
        ctk.CTkButton(path_frame, text="Initialise Path", width=120, command=initialise_setup_server_csv_dir).pack(side="left")
        ctk.CTkLabel(
            logging_section,
            text="Initialise creates Workcenter\\Station CSV files and a root products.csv for product lookup.",
            font=("Arial", 12),
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # Print Quantity Section
        pq_section = ctk.CTkFrame(container)
        pq_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(pq_section, text="Print Quantity", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        
        def validate_print_quantity(new_value):
            if new_value == "":
                return True
            try:
                value = int(new_value)
                return 1 <= value <= 10
            except ValueError:
                return False
                
        vcmd = (self.register(validate_print_quantity), '%P')
        
        self.print_quantity_var = ctk.StringVar(value=str(getattr(self, 'print_quantity', 2)))
        pq_entry = ctk.CTkEntry(
            pq_section, 
            textvariable=self.print_quantity_var,
            width=100,
            validate="key",
            validatecommand=vcmd
        )
        pq_entry.pack(padx=10, pady=(0, 10), anchor="w")
        ctk.CTkLabel(pq_section, text="Number of labels to print (1-10)", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(0, 10))

        # Printer tools
        printer_tools_section = ctk.CTkFrame(container)
        printer_tools_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(printer_tools_section, text="Printer Tools", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        ctk.CTkButton(
            printer_tools_section,
            text="Calibrate Zebra Printer",
            command=self.calibrate_zebra_printer,
            width=220,
        ).pack(anchor="w", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            printer_tools_section,
            text="Runs a Zebra media calibration for the labels currently loaded. The printer may feed a few labels while measuring.",
            font=("Arial", 12),
        ).pack(anchor="w", padx=10, pady=(0, 10))
        
        # Teraoka Section
        tk_section = ctk.CTkFrame(container)
        tk_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(tk_section, text="Teraoka", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        tk_switch = ctk.CTkSwitch(tk_section, text="Enabled", variable=self.teraoka_enabled, command=self._on_toggle_teraoka)
        tk_switch.pack(padx=10, pady=(0,10), anchor="w")

        # Auto Production Section
        auto_prod_section = ctk.CTkFrame(container)
        auto_prod_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(auto_prod_section, text="Automatic Production", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))

        # Auto Production Toggle
        auto_toggle_frame = ctk.CTkFrame(auto_prod_section, fg_color="transparent")
        auto_toggle_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkSwitch(auto_toggle_frame, text="Enable Auto Production", variable=self.auto_prod_enabled).pack(side="left", padx=5)

        # Time inputs for Auto Production
        time_frame = ctk.CTkFrame(auto_prod_section, fg_color="transparent")
        time_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(time_frame, text="Start:", font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkEntry(time_frame, textvariable=self.auto_start_time, width=70, font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkLabel(time_frame, text="Stop:", font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkEntry(time_frame, textvariable=self.auto_stop_time, width=70, font=("Arial", 12)).pack(side="left", padx=5)

        # Auto Downtime Section
        auto_downtime_section = ctk.CTkFrame(container)
        auto_downtime_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(auto_downtime_section, text="Auto Downtime", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))

        def validate_auto_downtime_multiplier(new_value):
            if new_value == "":
                return True
            try:
                value = float(new_value)
                return 1.0 <= value <= 20.0
            except ValueError:
                return False

        self.auto_downtime_multiplier_var = ctk.StringVar(
            value=self._format_auto_downtime_multiplier(self._get_auto_downtime_multiplier())
        )
        multiplier_frame = ctk.CTkFrame(auto_downtime_section, fg_color="transparent")
        multiplier_frame.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(multiplier_frame, text="Cycle Multiplier:", font=("Arial", 12)).pack(side="left", padx=5)
        multiplier_vcmd = (self.register(validate_auto_downtime_multiplier), "%P")
        multiplier_entry = ctk.CTkEntry(
            multiplier_frame,
            textvariable=self.auto_downtime_multiplier_var,
            width=90,
            font=("Arial", 12),
            validate="key",
            validatecommand=multiplier_vcmd,
        )
        multiplier_entry.pack(side="left", padx=5)
        self.enable_touch_keyboard(multiplier_entry)
        ctk.CTkLabel(multiplier_frame, text="x expected cycle", font=("Arial", 12)).pack(side="left", padx=5)

        # Overtime Section
        overtime_section = ctk.CTkFrame(container)
        overtime_section.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(overtime_section, text="Overtime", font=("Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 6))

        # Overtime Toggle
        overtime_toggle_frame = ctk.CTkFrame(overtime_section, fg_color="transparent")
        overtime_toggle_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkSwitch(overtime_toggle_frame, text="Enable Overtime", variable=self.overtime_enabled).pack(side="left", padx=5)

        # Time inputs for Overtime
        overtime_frame = ctk.CTkFrame(overtime_section, fg_color="transparent")
        overtime_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(overtime_frame, text="Start:", font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkEntry(overtime_frame, textvariable=self.overtime_start_time, width=70, font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkLabel(overtime_frame, text="Stop:", font=("Arial", 12)).pack(side="left", padx=5)
        ctk.CTkEntry(overtime_frame, textvariable=self.overtime_stop_time, width=70, font=("Arial", 12)).pack(side="left", padx=5)

        # Footer buttons
        footer = ctk.CTkFrame(container)
        footer.pack(fill="x", padx=10, pady=10)
        def save_changes():
            try:
                width_mm = float(self.setup_label_width_var.get())
                height_mm = float(self.setup_label_height_var.get())
                if width_mm <= 0 or height_mm <= 0:
                    raise ValueError("Label width and height must be greater than zero.")

                self._set_label_dimensions(width_mm, height_mm)

                zpl_content = zpl_text.get("1.0", "end-1c")
                if current_preset:
                    preset_path = current_preset_path or os.path.join(presets_dir, current_preset)
                    os.makedirs(os.path.dirname(preset_path), exist_ok=True)
                    zpl_content, zpl_errors, zpl_warnings = self._validate_zpl_template(zpl_content)
                    if zpl_errors:
                        raise ValueError("ZPL preset validation failed:\n" + "\n".join(zpl_errors))
                    if zpl_warnings and not messagebox.askyesno(
                        "ZPL Validation",
                        "The preset can be saved with warnings:\n\n"
                        + "\n".join(zpl_warnings)
                        + "\n\nContinue saving?",
                        parent=setup_popup,
                    ):
                        return
                    zpl_content = self._upsert_zpl_size_metadata(zpl_content, width_mm, height_mm)
                    with open(preset_path, 'w', encoding='utf-8') as f:
                        f.write(zpl_content)
                    zpl_text.delete("1.0", "end")
                    zpl_text.insert("1.0", zpl_content)

                print_quantity = int((self.print_quantity_var.get() or "").strip())
                if not 1 <= print_quantity <= 10:
                    raise ValueError("Print quantity must be between 1 and 10.")
                self.print_quantity = print_quantity

                auto_downtime_multiplier = (self.auto_downtime_multiplier_var.get() or "").strip()
                if not auto_downtime_multiplier:
                    raise ValueError("Auto downtime multiplier is required.")
                self._set_auto_downtime_multiplier(auto_downtime_multiplier)

                selected_backend = _normalize_logging_backend(self.setup_logging_backend_var.get())
                server_csv_dir = self.setup_server_csv_dir_var.get().strip()
                if selected_backend in {LOG_BACKEND_SERVER_CSV, LOG_BACKEND_BOTH} and not server_csv_dir:
                    raise ValueError("Server CSV directory is required when Server CSV is selected.")
                self.server_csv_dir = server_csv_dir
                self._set_logging_backend(selected_backend)
                if self._logging_backend_uses_server_csv():
                    if not self.test_server_csv_directory(show_dialog=False):
                        raise ValueError("Server CSV directory could not be initialised. Check the path and permissions.")

                # Ensure dropdown selection persists and prefs saved
                try:
                    if current_preset and hasattr(self, 'zpl_dropdown'):
                        self.zpl_dropdown.set(current_preset)
                        self._on_zpl_preset_changed(current_preset)
                    if hasattr(self, '_save_user_prefs'):
                        self._save_user_prefs()
                except Exception:
                    pass
                if current_preset:
                    messagebox.showinfo(
                        "Saved",
                        (
                            f"Changes saved to {current_preset}.\n"
                            f"Label size: {self._format_label_dimension(width_mm)} x "
                            f"{self._format_label_dimension(height_mm)} mm"
                        ),
                        parent=setup_popup,
                    )
                else:
                    messagebox.showinfo(
                        "Saved",
                        (
                            "Settings updated.\n"
                            f"Label size: {self._format_label_dimension(width_mm)} x "
                            f"{self._format_label_dimension(height_mm)} mm"
                        ),
                        parent=setup_popup,
                    )
                setup_popup.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Could not save: {e}", parent=setup_popup)
        ctk.CTkButton(footer, text="Save Changes", command=save_changes).pack(side="right", padx=10)

    def get_zebra_code(self):
        return self._zebra_code if hasattr(self, "_zebra_code") else self.default_zebra_code()

    def set_zebra_code(self, code):
        self._zebra_code = code

    def default_zebra_code(self):
        return """
^XA
^PW{width_dots}
^LL{height_dots}
... (rest of your ZPL code here) ...
^XZ
"""

    def open_zebra_editor(self):
        # Password prompt
        pw_popup = ctk.CTkToplevel(self)
        pw_popup.title("Password Required")
        pw_popup.geometry("400x250")  # Increased height for keyboard button
        pw_popup.lift()
        pw_popup.focus_force()
        pw_popup.grab_set()

        # Create a frame for the password input
        input_frame = ctk.CTkFrame(pw_popup)
        input_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(input_frame, text="Enter Password:", font=("Arial", 18)).pack(pady=(10, 5))
        
        # Create a frame for the password entry and keyboard button
        entry_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        entry_frame.pack(fill="x", pady=5)
        
        pw_var = ctk.StringVar()
        pw_entry = ctk.CTkEntry(entry_frame, textvariable=pw_var, font=("Arial", 18), show="*", width=250)
        pw_entry.pack(side="left", padx=(0, 5))
        self.enable_touch_keyboard(pw_entry)  # Enable touch keyboard for password entry
        
        # Add keyboard button
        keyboard_btn = ctk.CTkButton(
            entry_frame, 
            text="⌨️", 
            width=40, 
            command=self.show_onscreen_keyboard,
            font=("Arial", 16)
        )
        keyboard_btn.pack(side="left")
        
        # Bind focus event to show keyboard
        pw_entry.bind("<FocusIn>", lambda e: self.show_onscreen_keyboard())
        pw_entry.focus_set()

        def check_pw():
            if pw_var.get() == "2435":
                pw_popup.destroy()
                self.show_zebra_editor()
            else:
                messagebox.showerror("Access Denied", "Incorrect password.")

        ctk.CTkButton(pw_popup, text="Submit", command=check_pw).pack(pady=10)

    def show_zebra_editor(self):
        editor = ctk.CTkToplevel(self)
        editor.title("Zebra Printer Code Editor")
        editor.geometry("900x700")
        editor.lift()
        editor.focus_force()
        editor.grab_set()

        # Preset file dropdown
        preset_folder = ZPL_PRESETS_DIR
        preset_files = [os.path.basename(f) for f in glob.glob(os.path.join(preset_folder, "*.zpl"))]
        current_preset = self.zpl_preset.get() if hasattr(self, 'zpl_preset') else ''
        initial_preset = current_preset if current_preset in preset_files else (preset_files[0] if preset_files else "No presets found")
        preset_var = ctk.StringVar(value=initial_preset)

        def load_preset():
            selected = preset_var.get()
            if selected and selected != "No presets found":
                preset_path = self._resolve_zpl_preset_path(selected) or os.path.join(preset_folder, selected)
                with open(preset_path, "r", encoding='utf-8') as f:
                    preset_content = f.read()
                    zebra_text.delete("1.0", "end")
                    zebra_text.insert("1.0", preset_content)
                dimensions = self._extract_zpl_dimensions_mm(selected, preset_content)
                if dimensions:
                    label_width_var.set(str(dimensions[0]))
                    label_height_var.set(str(dimensions[1]))

        def browse_zpl_file():
            file_path = filedialog.askopenfilename(
                title="Select ZPL File",
                filetypes=[("Zebra Label Files", "*.zpl"), ("All Files", "*.*")]
            )
            if file_path:
                with open(file_path, "r", encoding='utf-8') as f:
                    preset_content = f.read()
                    zebra_text.delete("1.0", "end")
                    zebra_text.insert("1.0", preset_content)
                preset_var.set(os.path.basename(file_path))
                dimensions = self._extract_zpl_dimensions_mm(os.path.basename(file_path), preset_content)
                if dimensions:
                    label_width_var.set(str(dimensions[0]))
                    label_height_var.set(str(dimensions[1]))

        # --- Always show dropdown ---
        ctk.CTkLabel(editor, text="Choose Preset or Browse ZPL File:", font=("Arial", 16)).pack(pady=5)
        preset_menu = ctk.CTkOptionMenu(
            editor,
            values=preset_files if preset_files else ["No presets found"],
            variable=preset_var,
            command=lambda _: load_preset()
        )
        preset_menu.pack(pady=5)
        ctk.CTkButton(editor, text="Browse...", command=browse_zpl_file).pack(pady=5)

        # Label width/height
        ctk.CTkLabel(editor, text="LABEL_WIDTH (mm):", font=("Arial", 16)).pack(pady=5)
        label_width_var = ctk.StringVar(value=str(LABEL_WIDTH))
        width_entry = ctk.CTkEntry(editor, textvariable=label_width_var, font=("Arial", 16))
        width_entry.pack(pady=5)

        ctk.CTkLabel(editor, text="LABEL_HEIGHT (mm):", font=("Arial", 16)).pack(pady=5)
        label_height_var = ctk.StringVar(value=str(LABEL_HEIGHT))
        height_entry = ctk.CTkEntry(editor, textvariable=label_height_var, font=("Arial", 16))
        height_entry.pack(pady=5)

        # Zebra code editor
        editor_label_frame = ctk.CTkFrame(editor, fg_color="transparent")
        editor_label_frame.pack(fill="x", pady=(10, 0), padx=20)
        
        ctk.CTkLabel(editor_label_frame, text="Zebra Printer Code (ZPL):", font=("Arial", 16)).pack(side="left")
        
        # Add keyboard button next to the label
        keyboard_btn = ctk.CTkButton(
            editor_label_frame, 
            text="⌨️ Show Keyboard", 
            command=self.show_onscreen_keyboard,
            font=("Arial", 12),
            height=28
        )
        keyboard_btn.pack(side="right")
        
        zebra_code_var = ctk.StringVar(value=self.get_zebra_code())
        zebra_text = ctk.CTkTextbox(editor, font=("Consolas", 12), width=800, height=400)
        self.enable_touch_keyboard(zebra_text)  # Enable touch keyboard for Zebra code editor
        zebra_text.pack(pady=(0, 10), padx=20)
        zebra_text.insert("1.0", zebra_code_var.get())
        if preset_files and preset_var.get() != "No presets found":
            load_preset()
        
        # Bind focus event to show keyboard
        zebra_text.bind("<FocusIn>", lambda e: self.show_onscreen_keyboard())

        def save_changes():
            try:
                global LABEL_WIDTH, LABEL_HEIGHT
                LABEL_WIDTH = float(label_width_var.get())
                LABEL_HEIGHT = float(label_height_var.get())
                self.set_zebra_code(zebra_text.get("1.0", "end-1c"))
                messagebox.showinfo("Saved", "Settings updated.")
                editor.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Could not save: {e}")

        ctk.CTkButton(editor, text="Save Changes", command=save_changes).pack(pady=20)

    def get_zebra_code(self):
        return self._zebra_code if hasattr(self, "_zebra_code") else self.default_zebra_code()

    def set_zebra_code(self, code):
        self._zebra_code = code

    def default_zebra_code(self):
        return """
^XA
^PW{width_dots}
^LL{height_dots}
... (rest of your ZPL code here) ...
^XZ
"""
    # ------------------- SCAN HANDLER -------------------
    def handle_scan(
        self,
        event,
        increment_count=True,
        barcode_override=None,
        status='Scanned',
        notes='',
        is_rework=False,
        allow_duplicate_prompt=True,
        print_label_on_accept=True,
    ):
        barcode_source = barcode_override if barcode_override is not None else self.barcode_var.get()
        barcode = str(barcode_source).strip()
        normalized_barcode = self._normalize_barcode(barcode)
        scan_id = make_correlation_id("scan")
        scan_started_at = time.perf_counter()
        scan_outcome = "started"
        now = datetime.now()

        if self._scan_processing:
            LOGGER.warning(
                structured_message(
                    "scan_reentry_blocked",
                    barcode=normalized_barcode,
                    scan_id=scan_id,
                    active_scan_id=getattr(self, "_active_scan_id", ""),
                    active_barcode=self._active_scan_barcode,
                    status=status,
                    duration_ms=elapsed_ms(scan_started_at),
                )
            )
            return False

        self._scan_processing = True
        self._active_scan_barcode = normalized_barcode
        self._active_scan_id = scan_id

        try:
            log_event(
                LOGGER,
                logging.INFO,
                "scan_lifecycle_begin",
                barcode=normalized_barcode,
                scan_id=scan_id,
                status=status,
                is_rework=is_rework,
                increment_count=increment_count,
                duplicate_prompt_enabled=allow_duplicate_prompt,
                print_label_on_accept=print_label_on_accept,
            )

            # Check if production is running
            if not self.production_running:
                messagebox.showwarning("Production Not Running", "Please start production before scanning.")
                scan_outcome = "rejected_production_not_running"
                LOGGER.warning(
                    structured_message(
                        "scan_rejected_production_not_running",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        status=status,
                    )
                )
                return False

            # If Teraoka is enabled, require connection and job before scanning
            if self.teraoka_enabled.get():
                try:
                    connected = bool(self.teraoka and self.teraoka.is_connected())
                    job = (self.teraoka.current_job() if (self.teraoka and connected) else None)
                except Exception:
                    connected = False
                    job = None
                if not (connected and job):
                    messagebox.showwarning("Teraoka Not Ready", "Scanning is enabled only when Teraoka is connected and a job is received.")
                    scan_outcome = "rejected_teraoka_not_ready"
                    LOGGER.warning(
                        structured_message(
                            "scan_rejected_teraoka_not_ready",
                            barcode=normalized_barcode,
                            scan_id=scan_id,
                            status=status,
                            workcenter=self.current_workcenter,
                        )
                    )
                    return False

            # Check for empty barcode
            if not barcode:
                scan_outcome = "ignored_empty_barcode"
                return False

            # Check for duplicate barcode
            if allow_duplicate_prompt and self.is_duplicate_barcode(barcode):
                scan_outcome = "duplicate_routed_to_popup"
                log_event(LOGGER, logging.INFO, "scan_duplicate_routed_to_popup", barcode=normalized_barcode, scan_id=scan_id)
                self.handle_duplicate_barcode(barcode)
                return False

            # Get product info first
            product_code = self.product_var.get()
            product_info = self.get_product_info_from_sources(product_code)
            print(f"Product Info: {product_info}")  # Debug log

            description = product_info["description"] if product_info else "N/A"
            Barc = product_info["Barc"] if product_info else "N/A"
            PC = product_info["PC"] if product_info else "N/A"
            cycle_time_seconds = self._calculate_scan_cycle_time(now)

            # Queue the scan log first; only accepted scans proceed to count/print.
            log_requested = self.log_scan_to_excel(
                barcode,
                status=status,
                notes=notes,
                is_rework=is_rework,
                cycle_time_seconds=cycle_time_seconds,
                scan_id=scan_id,
            )
            if not log_requested:
                print(f"[WARNING] Scan log request failed for barcode: {barcode}")
                scan_outcome = "local_commit_rejected"
                LOGGER.error(
                    structured_message(
                        "scan_log_request_rejected",
                        barcode=normalized_barcode,
                        scan_id=scan_id,
                        status=status,
                        is_rework=is_rework,
                    )
                )
                messagebox.showerror("Logging Failed", "Failed to store the scan locally. The scan was not accepted.")
                self._set_health_signal("scan_write", HEALTH_ERROR, "Local scan commit failed")
                return False

            self.last_scanned_var.set(barcode)
            if increment_count:
                self.production_count += 1
                self.production_count_var.set(str(self.production_count))

            # Update GUI
            self.description_var.set(description)
            self._set_barcode_entry_value(Barc)
            self.PC_var.set(PC)
            self.last_scanned_var.set(barcode)

            # Use the previous scan timestamp for the current cycle before advancing it.
            self.cycle_time_var.set(f"{cycle_time_seconds:.2f} s")
            self.last_scan_time = now
            log_event(
                LOGGER,
                logging.INFO,
                "scan_accepted",
                barcode=normalized_barcode,
                scan_id=scan_id,
                status=status,
                is_rework=is_rework,
                increment_count=increment_count,
                cycle_time_seconds=round(cycle_time_seconds, 2),
                production_count=self.production_count,
            )

            if print_label_on_accept:
                # Print the label
                print(f"Printing label for barcode: {barcode}")  # Debug log
                success = self.print_label(
                    barcode_text=barcode,
                    description=description,
                    Barc=Barc,
                    PC=PC,
                    status=status,
                    scan_id=scan_id,
                )

                if not success:
                    scan_outcome = "accepted_print_failed"
                    messagebox.showwarning("Print Failed", "Failed to print the label. Please check the printer connection.")
                else:
                    scan_outcome = "accepted"
            else:
                scan_outcome = "accepted"

            # Update production metrics
            if self.start_time:
                self.total_runtime_seconds = (now - self.start_time).total_seconds()
                if self.total_runtime_seconds > 0:
                    pcs_per_min = calculate_pcs_per_min(self.production_count, self.total_runtime_seconds)
                    self.pcs_min_var.set(f"{pcs_per_min:.2f}")

            # Enqueue job receipt to Teraoka (non-blocking) only if enabled
            try:
                if self.teraoka_enabled.get() and hasattr(self, 'teraoka') and self.teraoka:
                    self.teraoka.enqueue_receipt(1)
            except Exception as e:
                print(f"Error enqueuing Teraoka receipt: {e}")
                LOGGER.exception(structured_message("teraoka_receipt_enqueue_failed", scan_id=scan_id, workcenter=self.current_workcenter))
                self._set_health_signal("teraoka", HEALTH_WARNING, "Receipt enqueue failed")

            return True

        except Exception as e:
            scan_outcome = "failed"
            messagebox.showerror("Error", f"Failed to process barcode: {str(e)}")
            print(f"Error in handle_scan: {traceback.format_exc()}")
            LOGGER.exception(
                structured_message(
                    "handle_scan_failed",
                    barcode=normalized_barcode,
                    scan_id=scan_id,
                    status=status,
                    is_rework=is_rework,
                )
            )
            self._set_health_signal("scan_write", HEALTH_ERROR, "Scan processing failed")
            return False
        finally:
            log_event(
                LOGGER,
                logging.INFO,
                "scan_lifecycle_complete",
                barcode=normalized_barcode,
                scan_id=scan_id,
                status=status,
                is_rework=is_rework,
                outcome=scan_outcome,
                duration_ms=elapsed_ms(scan_started_at),
            )
            self._active_scan_id = None
            self._active_scan_barcode = None
            self._scan_processing = False
            # Always clear the barcode field after processing
            self._clear_barcode_entry()
            self._schedule_scan_focus()

    def start_downtime_popup(self, reason, delay=None, stop_start=None):
        self.downtime_start = stop_start if isinstance(stop_start, datetime) else datetime.now()
        # For auto-detected or generic open, require operator to select a reason
        if reason in ("Auto Detected", "Select Reason", None, ""):
            self.downtime_reason = None
        else:
            self.downtime_reason = reason
        self.in_auto_downtime = (reason == "Auto Detected")

        self.popup = ctk.CTkToplevel(self)
        self.popup.attributes('-fullscreen', True)
        self.popup.configure(fg_color="#880000")
        self.popup.lift()  # Bring to front
        self.popup.focus_force()  # Grab focus
        self.popup.grab_set()     # Make modal

        self.downtime_timer_var.set("00:00:00")
        self.update_downtime_timer()

        # Reason label
        header_text = (
            "Downtime: Select Reason" if self.downtime_reason is None else f"Downtime: {self.downtime_reason}"
        )
        self.downtime_header_label = ctk.CTkLabel(
            self.popup,
            text=header_text,
            font=("Arial", 32),
            fg_color="#880000",
            text_color="white"
        )
        self.downtime_header_label.pack(pady=20)

        # Reason selection buttons inside popup
        reasons_frame = ctk.CTkFrame(self.popup, fg_color="transparent")
        reasons_frame.pack(pady=10)
        reasons = [
            "Mechanical Failure",
            "Material Shortage",
            "Quality Issue",
            "Changeover",
            "Operator Break",
            "Planned Maintenance"
        ]

        def select_reason(r):
            self.downtime_reason = r
            self.downtime_header_label.configure(text=f"Downtime: {r}")
            # Update non-editable selected reason field
            if hasattr(self, 'selected_reason_var'):
                self.selected_reason_var.set(r)
            self.check_resume_button_state()

        for idx, r in enumerate(reasons):
            btn = ctk.CTkButton(
                reasons_frame,
                text=r,
                font=("Arial", 12),
                fg_color="#aa0000",
                hover_color="#990000",
                text_color="white",
                width=200,
                command=lambda rr=r: select_reason(rr)
            )
            btn.grid(row=0, column=idx, padx=5, pady=5)

        # Last scan info (if available)
        if hasattr(self, "last_scanned_barcode"):
            ctk.CTkLabel(self.popup, text=f"Last Scan: {self.last_scanned_barcode}",
                         font=("Arial", 28), fg_color="#880000", text_color="white").pack(pady=10)
        if hasattr(self, "last_scanned_product"):
            ctk.CTkLabel(self.popup, text=f"Product: {self.last_scanned_product}",
                         font=("Arial", 24), fg_color="#880000", text_color="white").pack(pady=5)

        # Delay (only for auto-detected)
        if delay is not None:
            ctk.CTkLabel(self.popup, text=f"Delay: {delay:.2f} sec", font=("Arial", 24),
                         fg_color="#880000", text_color="white").pack(pady=20)

        # Timer
        self.timer_label = ctk.CTkLabel(self.popup, textvariable=self.downtime_timer_var,
                                        font=("Arial", 48), fg_color="#880000", text_color="white")
        self.timer_label.pack(pady=30)

        # --- SELECTED REASON (READ-ONLY) ---
        self.selected_reason_var = ctk.StringVar(value=(self.downtime_reason if self.downtime_reason else ""))
        ctk.CTkLabel(self.popup, text="Selected Reason:", font=("Arial", 24),
                     fg_color="#880000", text_color="white").pack(pady=(20, 5))
        self.selected_reason_entry = ctk.CTkEntry(self.popup, textvariable=self.selected_reason_var, font=("Arial", 20))
        self.selected_reason_entry.configure(state="disabled")
        self.selected_reason_entry.pack(pady=5)

        # --- OPERATOR INPUT FIELDS ---
        self.operator_name_var = ctk.StringVar()
        self.operator_reason_var = ctk.StringVar()

        ctk.CTkLabel(self.popup, text="Operator Name:", font=("Arial", 24),
                     fg_color="#880000", text_color="white").pack(pady=10)
        ctk.CTkEntry(self.popup, textvariable=self.operator_name_var, font=("Arial", 20)).pack(pady=5)

        ctk.CTkLabel(self.popup, text="Description:", font=("Arial", 24),
                     fg_color="#880000", text_color="white").pack(pady=10)
        ctk.CTkEntry(self.popup, textvariable=self.operator_reason_var, font=("Arial", 20)).pack(pady=5)

        # Resume button (start disabled until fields complete)
        self.resume_button = ctk.CTkButton(self.popup, text="Resume Production", font=("Arial", 24),
                                           fg_color="green", command=self.resume_production, state="disabled")
        self.resume_button.pack(pady=20)

        # Enable/disable resume button based on fields
        self.operator_name_var.trace_add("write", lambda *args: self.check_resume_button_state())
        self.operator_reason_var.trace_add("write", lambda *args: self.check_resume_button_state())

        # Footer text
        ctk.CTkLabel(self.popup, text="Giving Reasons helps us Improve...",
                     font=("Arial", 20), fg_color="#880000", text_color="white").pack(pady=40)

        self.popup.transient(self)
        self.popup.grab_set()

    def check_resume_button_state(self, *args):
        """Enable Resume button only when reason selected, operator name and description are provided."""
        try:
            enabled = resume_button_enabled(
                self.operator_name_var.get(),
                self.downtime_reason,
                self.operator_reason_var.get(),
            )
            if hasattr(self, 'resume_button'):
                self.resume_button.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def resume_production(self):
        # Get operator info
        operator_name = self.operator_name_var.get()
        operator_reason = self.operator_reason_var.get() or self.downtime_reason
        reason2 = self.downtime_reason
        # Calculate downtime duration
        end_time = datetime.now()
        duration = (end_time - self.downtime_start).total_seconds()

        downtime_row = build_downtime_event_row(
            timestamp=self.downtime_start,
            duration_seconds=duration,
            reason=reason2 or 'Unknown',
            description=operator_reason,
            operator=operator_name,
            workcenter=self.current_workcenter,
        )
        try:
            downtime_event_id = self._commit_local_downtime_event(downtime_row)
        except Exception:
            LOGGER.exception(
                structured_message(
                    "downtime_resume_local_commit_failed",
                    reason=reason2 or "Unknown",
                    workcenter=self.current_workcenter,
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_ERROR, "Downtime commit failed")
            messagebox.showerror("Storage Error", "Failed to store the downtime locally. Production was not resumed.")
            return

        # Reset popup and flags
        self.in_auto_downtime = False
        self.downtime_start = None
        self.downtime_reason = None
        self.popup.destroy()
        self._start_downtime_sync_worker(downtime_event_id, "Downtime")
        self._schedule_scan_focus()

        self.last_scan_time = end_time
        # Optionally reset operator fields
        self.operator_name_var.set("")
        self.operator_reason_var.set("")
        log_event(
            LOGGER,
            logging.INFO,
            "downtime_logged_and_resumed",
            reason=reason2 or "Unknown",
            workcenter=self.current_workcenter,
            duration_seconds=f"{duration:.2f}",
        )


    def update_downtime_timer(self):
        if self.downtime_start:
            elapsed = datetime.now() - self.downtime_start
            self.downtime_timer_var.set(str(elapsed).split('.')[0])
            self.popup.after(1000, self.update_downtime_timer)

    def end_downtime(self):
        end = datetime.now()
        duration = (end - self.downtime_start).total_seconds()
        downtime_row = build_downtime_event_row(
            timestamp=self.downtime_start,
            duration_seconds=duration,
            reason=self.downtime_reason or 'Unknown',
            description='',
            operator='',
            workcenter=self.current_workcenter,
        )
        try:
            downtime_event_id = self._commit_local_downtime_event(downtime_row)
        except Exception:
            LOGGER.exception(
                structured_message(
                    "downtime_end_local_commit_failed",
                    reason=self.downtime_reason or "Unknown",
                    workcenter=self.current_workcenter,
                    db_path=self.local_db_file,
                )
            )
            self._set_health_signal("local_store", HEALTH_ERROR, "Downtime commit failed")
            messagebox.showerror("Storage Error", "Failed to store the downtime locally.")
            return
         

        self.popup.destroy()
        self.in_auto_downtime = False
        self._start_downtime_sync_worker(downtime_event_id, "Downtime")
        log_event(
            LOGGER,
            logging.INFO,
            "downtime_ended",
            reason=self.downtime_reason or "Unknown",
            workcenter=self.current_workcenter,
            duration_seconds=f"{duration:.2f}",
        )

    def update_printer_status(self):
        started_at = time.perf_counter()
        target = ""
        outcome = "unknown"
        try:
            # Enumerate available printers (local + connections)
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags)
            names = [p[2] for p in printers if len(p) > 2]
            try:
                print(f"[Printer] Found printers: {names}")
            except Exception:
                pass

            # Try exact (case-insensitive) match first
            target = None
            for n in names:
                if n.strip().lower() == ZEBRA_PRINTER_NAME.strip().lower():
                    target = n
                    break
            # Fallback: any printer containing zebra/zdesigner
            if target is None:
                for n in names:
                    ln = n.strip().lower()
                    if 'zebra' in ln or 'zdesigner' in ln:
                        target = n
                        break

            if target is None:
                self.printer_status_var.set("Printer Status: NOT CONNECTED")
                self._set_health_signal("printer", HEALTH_WARNING, "Not connected")
                outcome = "not_connected"
                try:
                    self.printer_status_label.configure(text_color="red")
                    self.printer_status_value_label.configure(text_color="red")
                except Exception:
                    pass
                return

            # Open and read detailed flags
            hPrinter = win32print.OpenPrinter(target)
            try:
                info2 = win32print.GetPrinter(hPrinter, 2)
                status = info2.get('Status', 0)
                attrs = info2.get('Attributes', 0)

                offline_flags = (
                    (status & win32print.PRINTER_STATUS_OFFLINE) or
                    (attrs & getattr(win32print, 'PRINTER_ATTRIBUTE_WORK_OFFLINE', 0)) or
                    (status & getattr(win32print, 'PRINTER_STATUS_NOT_AVAILABLE', 0))
                )
                error_flags = (
                    status & (
                        getattr(win32print, 'PRINTER_STATUS_ERROR', 0) |
                        getattr(win32print, 'PRINTER_STATUS_PAPER_OUT', 0) |
                        getattr(win32print, 'PRINTER_STATUS_PAPER_JAM', 0) |
                        getattr(win32print, 'PRINTER_STATUS_TONER_LOW', 0) |
                        getattr(win32print, 'PRINTER_STATUS_NO_TONER', 0)
                    )
                )

                if offline_flags:
                    self.printer_status_var.set(f"Printer Status: OFFLINE ({target})")
                    self._set_health_signal("printer", HEALTH_WARNING, f"Offline: {target}")
                    outcome = "offline"
                    try:
                        self.printer_status_label.configure(text_color="red")
                        self.printer_status_value_label.configure(text_color="red")
                    except Exception:
                        pass
                elif error_flags:
                    self.printer_status_var.set(f"Printer Status: ERROR/NOT READY ({target})")
                    self._set_health_signal("printer", HEALTH_WARNING, f"Not ready: {target}")
                    outcome = "not_ready"
                    try:
                        self.printer_status_label.configure(text_color="orange")
                        self.printer_status_value_label.configure(text_color="orange")
                    except Exception:
                        pass
                else:
                    self.printer_status_var.set(f"Printer Status: READY ({target})")
                    self._set_health_signal("printer", HEALTH_OK, f"Ready: {target}")
                    outcome = "ready"
                    try:
                        self.printer_status_label.configure(text_color="green")
                        self.printer_status_value_label.configure(text_color="green")
                    except Exception:
                        pass
            finally:
                win32print.ClosePrinter(hPrinter)
        except Exception as e:
            outcome = "failed"
            self.printer_status_var.set(f"Printer Status: ERROR ({e})")
            LOGGER.exception(structured_message("printer_status_poll_failed"))
            self._set_health_signal("printer", HEALTH_ERROR, "Status poll failed")
            try:
                self.printer_status_label.configure(text_color="red")
                self.printer_status_value_label.configure(text_color="red")
            except Exception:
                pass
        finally:
            log_timing(
                LOGGER,
                logging.DEBUG,
                "printer_status_poll_timing",
                started_at,
                min_duration_ms=500,
                outcome=outcome,
                printer_name=target or "",
            )

    def poll_printer_status(self):
        self.update_printer_status()
        try:
            self._apply_status_colors()
        except Exception:
            pass
        self.after(5000, self.poll_printer_status)  # Check every 5 seconds



    def _set_label_color(self, label, color):
        set_label_color(label, color)

    def _apply_status_colors(self):
        try:
            # Production state
            state = (self.production_state_var.get() or "").strip().upper()
            # Try to find the production state label and update its color
            try:
                # Look for the label that displays production state
                for widget in self.winfo_children():
                    if isinstance(widget, ctk.CTkFrame):
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkFrame):
                                for grandchild in child.winfo_children():
                                    if hasattr(grandchild, 'cget') and grandchild.cget('textvariable') == str(self.production_state_var):
                                        grandchild.configure(text_color="green" if state == "RUNNING" else ("orange" if state == "" or state == "N/A" else "red"))
                                        break
            except Exception:
                pass  # If we can't find the label, just skip color update

            # Last scanned
            last_scanned = (self.last_scanned_var.get() or "").strip()
            try:
                for widget in self.winfo_children():
                    if isinstance(widget, ctk.CTkFrame):
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkFrame):
                                for grandchild in child.winfo_children():
                                    if hasattr(grandchild, 'cget') and grandchild.cget('textvariable') == str(self.last_scanned_var):
                                        grandchild.configure(text_color="green" if last_scanned else "orange")
                                        break
            except Exception:
                pass

            # Cycle time
            cyc_text = (self.cycle_time_var.get() or "").strip().lower()
            is_defined = cyc_text not in ("", "n/a", "0.00 s", "0 s")
            try:
                for widget in self.winfo_children():
                    if isinstance(widget, ctk.CTkFrame):
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkFrame):
                                for grandchild in child.winfo_children():
                                    if hasattr(grandchild, 'cget') and grandchild.cget('textvariable') == str(self.cycle_time_var):
                                        grandchild.configure(text_color="green" if is_defined else "orange")
                                        break
            except Exception:
                pass

            # PCS/min
            try:
                pcs = float(self.pcs_min_var.get())
            except Exception:
                pcs = 0.0
            try:
                for widget in self.winfo_children():
                    if isinstance(widget, ctk.CTkFrame):
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkFrame):
                                for grandchild in child.winfo_children():
                                    if hasattr(grandchild, 'cget') and grandchild.cget('textvariable') == str(self.pcs_min_var):
                                        grandchild.configure(text_color="green" if pcs > 0 else "orange")
                                        break
            except Exception:
                pass
        except Exception as e:
            print(f"[WARNING] Failed to apply status colors: {e}")

        # Printer (mirror info bar color)
        try:
            # if info label has color, copy; else derive from text
            txt = (self.printer_status_var.get() or "").upper()
            color = "green" if "READY" in txt else ("red" if "OFFLINE" in txt or "ERROR" in txt or "NOT CONNECTED" in txt else "orange")
            self._set_label_color(self.printer_status_value_label, color)
        except Exception:
            pass

        # Teraoka
        try:
            ttxt = (self.teraoka_status_var.get() or "").upper()
            # Important: 'DISCONNECTED' contains 'CONNECTED', so test red cases first
            tcolor = ("red" if ("DISCONNECTED" in ttxt or "ERROR" in ttxt)
                      else ("green" if "CONNECTED" in ttxt else "orange"))
            self._set_label_color(self.teraoka_status_value_label, tcolor)
            jtxt = (self.teraoka_job_var.get() or "").strip()
            self._set_label_color(self.teraoka_job_value_label, "green" if jtxt and jtxt != "Job: -" else "orange")
        except Exception:
            pass

    def write_graph_data_to_csv(self):
        try:
            # Create a folder for graph logs if it doesn't exist
            log_folder = "graph_logs"
            os.makedirs(log_folder, exist_ok=True)
            # Use product and date for filename
            date_str = self.start_time.strftime("%Y-%m-%d_%H-%M-%S") if self.start_time else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            product = self.product_var.get().replace(" ", "_")
            filename = f"{product}_{date_str}.csv"
            filepath = os.path.join(log_folder, filename)
            with open(filepath, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Timestamp (s)", "PCS/min"])
                for t, pcs in zip(self.timestamps, self.cycle_times):
                    writer.writerow([t, pcs])
        except Exception as e:
            print("Error writing graph data to CSV:", e)

    def update_live_labels(self):
        # PCS/min: production count / elapsed time in minutes
        pcs_min = 0.0
        if self.start_time and self.production_count > 0:
            elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
            elapsed_minutes = elapsed_seconds / 60 if elapsed_seconds > 0 else 1
            pcs_min = self.production_count / elapsed_minutes
        self.pcs_min_var.set(f"{pcs_min:.2f}")

        # Current cycle timer: time since last scan
        if self.last_scan_time:
            delay = (datetime.now() - self.last_scan_time).total_seconds()
            self.current_cycle_timer_var.set(f"{delay:.2f} s")
        else:
            self.current_cycle_timer_var.set("0.00 s")

        self.after(1000, self.update_live_labels)

    def toggle_zpl_presets(self):
        """Toggle the visibility of the ZPL presets content"""
        if self.zpl_content_visible:
            self.zpl_content.pack_forget()
            self.zpl_header.configure(text="▶ ZPL Presets")
        else:
            self.zpl_content.pack(fill="x", expand=True, pady=5)
            self.zpl_header.configure(text="▼ ZPL Presets")
        self.zpl_content_visible = not self.zpl_content_visible

    def _resolve_zpl_preset_path(self, preset_name=None):
        selected_preset = str(
            preset_name if preset_name is not None else (self.zpl_preset.get() if hasattr(self, 'zpl_preset') else '')
        ).strip()
        return resolve_zpl_preset_path(selected_preset, getattr(self, 'custom_zpl_presets_dir', None), ZPL_PRESETS_DIR)

    def _format_label_dimension(self, value):
        return format_label_dimension(value)

    def _set_label_dimensions(self, width_mm, height_mm):
        global LABEL_WIDTH, LABEL_HEIGHT
        LABEL_WIDTH = float(width_mm)
        LABEL_HEIGHT = float(height_mm)

        width_text = self._format_label_dimension(LABEL_WIDTH)
        height_text = self._format_label_dimension(LABEL_HEIGHT)

        for attr_name, attr_value in (
            ("setup_label_width_var", width_text),
            ("setup_label_height_var", height_text),
        ):
            try:
                text_var = getattr(self, attr_name, None)
                if text_var is not None:
                    text_var.set(attr_value)
            except Exception:
                pass

    def _upsert_zpl_size_metadata(self, zpl_template, width_mm, height_mm):
        return upsert_zpl_size_metadata(zpl_template, width_mm, height_mm)

    def _extract_zpl_dimensions_mm(self, preset_name="", zpl_template=""):
        return extract_zpl_dimensions_mm(preset_name, zpl_template)

    def _apply_selected_zpl_preset_dimensions(self, preset_name=None, zpl_template=""):
        selected_preset = str(
            preset_name if preset_name is not None else (self.zpl_preset.get() if hasattr(self, 'zpl_preset') else '')
        ).strip()
        if not selected_preset:
            return None

        template_text = zpl_template
        if not template_text:
            preset_path = self._resolve_zpl_preset_path(selected_preset)
            if preset_path:
                try:
                    with open(preset_path, 'r', encoding='utf-8') as f:
                        template_text = f.read()
                except Exception as e:
                    print(f"Error reading ZPL preset for dimensions: {e}")

        dimensions = self._extract_zpl_dimensions_mm(selected_preset, template_text)
        if not dimensions:
            return None

        self._set_label_dimensions(*dimensions)
        print(f"Applied preset size: {selected_preset} -> {LABEL_WIDTH}mm x {LABEL_HEIGHT}mm")
        return dimensions

    def _coerce_print_quantity(self):
        raw_quantity = None
        try:
            if hasattr(self, 'print_quantity_var') and self.print_quantity_var is not None:
                raw_quantity = self.print_quantity_var.get()
        except Exception:
            raw_quantity = None

        quantity = coerce_print_quantity(raw_quantity, getattr(self, 'print_quantity', 2))
        self.print_quantity = quantity
        try:
            if hasattr(self, 'print_quantity_var') and self.print_quantity_var is not None:
                self.print_quantity_var.set(str(quantity))
        except Exception:
            pass
        return quantity

    def _format_auto_downtime_multiplier(self, value):
        return format_auto_downtime_multiplier(value)

    def _set_auto_downtime_multiplier(self, value):
        multiplier = coerce_auto_downtime_multiplier(value)
        self.auto_downtime_multiplier = multiplier
        try:
            if hasattr(self, "auto_downtime_multiplier_var") and self.auto_downtime_multiplier_var is not None:
                self.auto_downtime_multiplier_var.set(self._format_auto_downtime_multiplier(multiplier))
        except Exception:
            pass
        return multiplier

    def _get_auto_downtime_multiplier(self):
        try:
            return self._set_auto_downtime_multiplier(getattr(self, "auto_downtime_multiplier", 2.5))
        except Exception:
            self.auto_downtime_multiplier = 2.5
            return 2.5

    def _sanitize_zpl_payload(self, zpl_code):
        return sanitize_zpl_payload(zpl_code)

    def _validate_zpl_template(self, zpl_code):
        return validate_zpl_template(zpl_code, ZPL_ALLOWED_PLACEHOLDERS)

    def _prepare_zpl_print_job(self, zpl_code, quantity):
        return prepare_zpl_print_job(zpl_code, quantity)

    def _build_zpl_preview_payload(self, zpl_template):
        preset_name = self._selected_zpl_preset_name()
        dimensions = self._extract_zpl_dimensions_mm(preset_name, zpl_template) or (LABEL_WIDTH, LABEL_HEIGHT)
        width_mm, height_mm = dimensions
        dpi = 203
        width_dots = int(width_mm * dpi / 25.4)
        height_dots = int(height_mm * dpi / 25.4)

        product_code = ""
        barcode_text = ""
        try:
            product_code = str(self.product_var.get() or "").strip()
        except Exception:
            product_code = ""
        try:
            barcode_text = str(self.barcode_var.get() or "").strip()
        except Exception:
            barcode_text = ""
        if not barcode_text:
            try:
                barcode_text = str(self.last_scanned_var.get() or "").strip()
            except Exception:
                barcode_text = ""
        if not barcode_text:
            barcode_text = "SAMPLE123456"

        product_info = self.get_product_info_from_sources(product_code) if product_code else None
        description = product_info["description"] if product_info else "Sample Pump"
        barc = product_info["Barc"] if product_info else barcode_text
        pc = product_info["PC"] if product_info else (product_code or "SAMPLE-PC")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        context = {
            "width_dots": width_dots,
            "height_dots": height_dots,
            "barcode_text": barcode_text,
            "description": description,
            "Barc": barc,
            "PC": pc,
            "batch_code": f"{barcode_text[:5]}{datetime.now().strftime('%d%m')}",
            "timestamp": timestamp,
            "desc1": description[:28],
            "desc2": description[29:] if len(description) > 29 else "",
        }

        class _PreviewFormatMap(dict):
            def __missing__(self, key):
                return "{" + str(key) + "}"

        try:
            rendered_zpl = str(zpl_template or "").format_map(_PreviewFormatMap(context))
        except Exception:
            rendered_zpl = str(zpl_template or "")
        rendered_zpl = self._sanitize_zpl_payload(rendered_zpl)
        return rendered_zpl, context, width_mm, height_mm

    def _zpl_command_tokens(self, zpl_code):
        return zpl_command_tokens(zpl_code)

    def _load_preview_font(self, size, bold=False):
        try:
            from PIL import ImageFont
            candidates = ["arialbd.ttf" if bold else "arial.ttf", "calibrib.ttf" if bold else "calibri.ttf"]
            for font_name in candidates:
                try:
                    return ImageFont.truetype(font_name, max(8, int(size)))
                except Exception:
                    continue
            return ImageFont.load_default()
        except Exception:
            return None

    def _code128_patterns(self):
        return code128_patterns()

    def _draw_code128_barcode(self, draw, x, y, data, module_width, height, show_text=True):
        patterns = self._code128_patterns()
        clean_data = "".join(ch for ch in str(data or "") if 32 <= ord(ch) <= 126)
        if not clean_data:
            clean_data = "SAMPLE123456"

        codes = [104] + [ord(ch) - 32 for ch in clean_data]
        checksum = 104
        for index, code in enumerate(codes[1:], start=1):
            checksum += index * code
        codes.extend([checksum % 103, 106])

        cursor = int(x)
        top = int(y)
        bottom = int(y + max(12, height))
        module_width = max(1, int(module_width))
        for code in codes:
            pattern = patterns[code]
            is_bar = True
            for width_char in pattern:
                segment_width = int(width_char) * module_width
                if is_bar:
                    draw.rectangle([cursor, top, cursor + segment_width - 1, bottom], fill="black")
                cursor += segment_width
                is_bar = not is_bar

        if show_text:
            font = self._load_preview_font(max(12, int(height * 0.12)))
            try:
                text_bbox = draw.textbbox((0, 0), clean_data, font=font)
                text_width = text_bbox[2] - text_bbox[0]
            except Exception:
                text_width = len(clean_data) * 8
            text_x = int(x + max(0, (cursor - x - text_width) / 2))
            draw.text((text_x, bottom + 6), clean_data, fill="black", font=font)

    def _draw_zpl_text(self, draw, xy, text, font_size, font_width=None):
        font = self._load_preview_font(font_size)
        x, y = xy
        for offset, line in enumerate(str(text or "").replace("\\&", "\n").splitlines() or [""]):
            draw.text((int(x), int(y + offset * max(10, font_size + 4))), line, fill="black", font=font)

    def _render_zpl_preview_image(self, zpl_code, fallback_width_mm=None, fallback_height_mm=None):
        from PIL import Image as PILImage, ImageDraw

        dpi = 203
        width_match = re.search(r'\^PW(\d+)', str(zpl_code or ""), re.IGNORECASE)
        height_match = re.search(r'\^LL(\d+)', str(zpl_code or ""), re.IGNORECASE)
        width_dots = int(width_match.group(1)) if width_match else int(float(fallback_width_mm or LABEL_WIDTH) * dpi / 25.4)
        height_dots = int(height_match.group(1)) if height_match else int(float(fallback_height_mm or LABEL_HEIGHT) * dpi / 25.4)
        width_dots = max(200, min(2400, width_dots))
        height_dots = max(200, min(2400, height_dots))

        image = PILImage.new("RGB", (width_dots, height_dots), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width_dots - 1, height_dots - 1], outline="#333333", width=2)

        x = 0
        y = 0
        label_home_x = 0
        label_home_y = 0
        font_size = 30
        by_width = 2
        by_height = 100
        pending_barcode = None
        notes = []

        def parse_ints(args, limit=None):
            parts = [part.strip() for part in str(args or "").split(",")]
            values = []
            for part in parts[:limit] if limit else parts:
                try:
                    values.append(int(float(part)))
                except Exception:
                    values.append(None)
            return values

        for _marker, command, args in self._zpl_command_tokens(zpl_code):
            if command == "LH":
                values = parse_ints(args, 2)
                label_home_x = values[0] or 0 if values else 0
                label_home_y = values[1] or 0 if len(values) > 1 else 0
            elif command in {"FO", "FT"}:
                values = parse_ints(args, 2)
                if values:
                    x = label_home_x + (values[0] or 0)
                    y = label_home_y + (values[1] or 0)
                    if command == "FT":
                        y = max(0, y - font_size)
                pending_barcode = None
            elif command == "CF":
                values = parse_ints(",".join(str(args or "").split(",")[1:]), 2)
                if values and values[0]:
                    font_size = max(8, values[0])
            elif command.startswith("A") and command not in {"AC", "AD"}:
                values = parse_ints(",".join(str(args or "").split(",")[1:]), 2)
                if values and values[0]:
                    font_size = max(8, values[0])
            elif command == "BY":
                values = parse_ints(args, 3)
                if values and values[0]:
                    by_width = max(1, values[0])
                if len(values) >= 3 and values[2]:
                    by_height = max(20, values[2])
            elif command == "BC":
                params = [part.strip().upper() for part in str(args or "").split(",")]
                height = by_height
                if len(params) > 1 and params[1]:
                    try:
                        height = int(float(params[1]))
                    except Exception:
                        pass
                show_text = True
                if len(params) > 2 and params[2] == "N":
                    show_text = False
                pending_barcode = {"kind": "code128", "height": height, "show_text": show_text}
            elif command in {"BQ", "BX"}:
                pending_barcode = {"kind": command, "height": by_height, "show_text": False}
            elif command == "GB":
                values = parse_ints(args, 3)
                box_width = values[0] or 1 if values else 1
                box_height = values[1] or 1 if len(values) > 1 else 1
                thickness = max(1, values[2] or 1 if len(values) > 2 else 1)
                if box_width <= thickness or box_height <= thickness:
                    draw.rectangle([x, y, x + box_width, y + box_height], fill="black")
                else:
                    for offset in range(thickness):
                        draw.rectangle([x + offset, y + offset, x + box_width - offset, y + box_height - offset], outline="black")
            elif command == "GF":
                values = parse_ints(args, 4)
                total_bytes = values[1] or 0 if len(values) > 1 else 0
                bytes_per_row = values[3] or values[2] or 0 if len(values) > 3 else 0
                graphic_width = max(80, bytes_per_row * 8)
                graphic_height = max(40, int(total_bytes / bytes_per_row) if bytes_per_row else 60)
                draw.rectangle([x, y, x + graphic_width, y + graphic_height], outline="#555555", fill="#efefef")
                self._draw_zpl_text(draw, (x + 8, y + 8), "Graphic", 18)
                if "Graphic fields are shown as placeholders." not in notes:
                    notes.append("Graphic fields are shown as placeholders.")
            elif command == "FD":
                field_text = str(args or "")
                if pending_barcode:
                    if pending_barcode["kind"] == "code128":
                        self._draw_code128_barcode(
                            draw,
                            x,
                            y,
                            field_text,
                            by_width,
                            pending_barcode["height"],
                            show_text=pending_barcode["show_text"],
                        )
                    else:
                        size = max(70, min(180, pending_barcode["height"]))
                        draw.rectangle([x, y, x + size, y + size], outline="black", width=3)
                        self._draw_zpl_text(draw, (x + 8, y + 8), pending_barcode["kind"], 18)
                        notes.append(f"^{pending_barcode['kind']} barcode is shown as a placeholder.")
                    pending_barcode = None
                else:
                    self._draw_zpl_text(draw, (x, y), field_text, font_size)

        return image, notes

    def _fit_preview_image(self, image, max_width=680, max_height=620):
        return fit_preview_image(image, max_width, max_height)

    def load_zpl_preset_names(self):
        """Load just the filenames of available ZPL presets"""
        presets, errors = load_zpl_preset_names_from_dirs(getattr(self, 'custom_zpl_presets_dir', ''), ZPL_PRESETS_DIR)
        for error in errors:
            print(error)
        return presets
        
    def load_zpl_presets(self):
        """Load available ZPL presets with full paths"""
        return zpl_preset_paths(os.path.dirname(os.path.abspath(__file__)), self.load_zpl_preset_names())
    
    def refresh_zpl_presets(self):
        """Refresh the list of available ZPL presets"""
        current_selection = self.zpl_dropdown.get()
        presets = self.load_zpl_preset_names()
        self.zpl_dropdown.configure(values=presets)
        
        # Try to restore the previous selection if it still exists
        if current_selection in presets:
            self.zpl_dropdown.set(current_selection)
        elif presets:  # Otherwise select the first one if available
            self.zpl_dropdown.set(presets[0])
        self._on_zpl_preset_changed(self.zpl_dropdown.get() if presets else None)
            
        messagebox.showinfo("Info", f"Refreshed ZPL presets. Found {len(presets)} presets.")
        try:
            self._save_user_prefs()
        except Exception:
            pass
    
    def get_zpl_template(self):
        """Get the content of the selected ZPL template"""
        try:
            selected_preset = self.zpl_preset.get() if hasattr(self, 'zpl_preset') else ''
            preset_path = self._resolve_zpl_preset_path(selected_preset)
            if preset_path:
                with open(preset_path, 'r', encoding='utf-8') as f:
                    return f.read()
            return None
        except Exception as e:
            print(f"Error loading ZPL template: {e}")
            return None
    
    def preview_zpl(self):
        """Show a rendered preview of the ZPL label and the generated ZPL code."""
        try:
            zpl_template = self.get_zpl_template()
            if not zpl_template:
                messagebox.showwarning("No Template", "No ZPL template selected or template is empty.", parent=self)
                return

            rendered_zpl, preview_context, width_mm, height_mm = self._build_zpl_preview_payload(zpl_template)
            label_image, render_notes = self._render_zpl_preview_image(rendered_zpl, width_mm, height_mm)
            display_image = self._fit_preview_image(label_image)

            preview_window = ctk.CTkToplevel(self)
            preview_window.title("ZPL Preview")
            preview_window.geometry("980x760")
            preview_window.minsize(780, 560)

            header_frame = ctk.CTkFrame(preview_window)
            header_frame.pack(fill="x", padx=10, pady=(10, 5))
            preset_name = self._selected_zpl_preset_name() or "Current template"
            ctk.CTkLabel(
                header_frame,
                text=(
                    f"{preset_name} | {self._format_label_dimension(width_mm)} x "
                    f"{self._format_label_dimension(height_mm)} mm | "
                    f"Sample serial: {preview_context.get('barcode_text', '')}"
                ),
                font=("Arial", 14, "bold"),
                anchor="w",
            ).pack(fill="x", padx=10, pady=8)

            tabview = ctk.CTkTabview(preview_window)
            tabview.pack(fill="both", expand=True, padx=10, pady=5)
            preview_tab = tabview.add("Label Preview")
            code_tab = tabview.add("ZPL Code / Test")

            visual_frame = ctk.CTkScrollableFrame(preview_tab)
            visual_frame.pack(fill="both", expand=True, padx=5, pady=5)
            preview_window._zpl_preview_image = ctk.CTkImage(
                light_image=display_image,
                dark_image=display_image,
                size=display_image.size,
            )
            ctk.CTkLabel(
                visual_frame,
                image=preview_window._zpl_preview_image,
                text="",
            ).pack(padx=10, pady=10)

            if render_notes:
                ctk.CTkLabel(
                    visual_frame,
                    text="; ".join(sorted(set(render_notes))),
                    font=("Arial", 11),
                    text_color="orange",
                    anchor="w",
                ).pack(fill="x", padx=10, pady=(0, 10))

            zpl_text = ctk.CTkTextbox(code_tab, width=880, height=540)
            zpl_text.insert("1.0", rendered_zpl)
            self.enable_touch_keyboard(zpl_text)
            zpl_text.configure(state="disabled")
            zpl_text.pack(pady=10, padx=10, fill="both", expand=True)

            button_frame = ctk.CTkFrame(preview_window, fg_color="transparent")
            button_frame.pack(fill="x", padx=10, pady=(5, 10))
            ctk.CTkButton(
                button_frame,
                text="Print Test Label",
                command=lambda: self.print_preview(rendered_zpl),
                width=160,
            ).pack(side="right", padx=5)

            def _on_close():
                try:
                    preview_window.grab_release()
                    preview_window.attributes('-topmost', False)
                except Exception:
                    pass
                preview_window.destroy()

            ctk.CTkButton(button_frame, text="Close", command=_on_close, width=100).pack(side="right", padx=5)
            preview_window.protocol("WM_DELETE_WINDOW", _on_close)
            self._present_app_dialog(preview_window)

        except Exception as e:
            messagebox.showerror("Preview Error", f"Error generating preview: {str(e)}", parent=self)
            LOGGER.exception(structured_message("zpl_visual_preview_failed"))
            
    def _is_printer_available(self, printer_name=None):
        """Return True if the given (or default) printer appears online/available."""
        try:
            return printer_is_available(win32print, printer_name)
        except Exception:
            LOGGER.exception(
                structured_message(
                    "printer_availability_check_failed",
                    printer_name=printer_name,
                )
            )
            self._set_health_signal("printer", HEALTH_ERROR, "Availability check failed")
            return False

    def _send_raw_printer_job(self, raw_data, printer_name=None, job_name="Zebra Command"):
        started_at = time.perf_counter()
        outcome = "started"
        payload = raw_data.encode('utf-8') if isinstance(raw_data, str) else raw_data
        target_printer = printer_name or ZEBRA_PRINTER_NAME

        try:
            if not self._is_printer_available(target_printer):
                outcome = "unavailable"
                raise RuntimeError(f"Zebra printer {target_printer} is offline or unavailable.")

            payload = send_raw_printer_job(win32print, payload, target_printer, job_name)
            outcome = "sent"
        except Exception:
            if outcome == "started":
                outcome = "failed"
            raise
        finally:
            log_timing(
                LOGGER,
                logging.DEBUG,
                "raw_printer_job_timing",
                started_at,
                min_duration_ms=0,
                outcome=outcome,
                printer_name=target_printer,
                job_name=job_name,
                payload_bytes=len(payload or b""),
            )

    def calibrate_zebra_printer(self):
        printer_name = ZEBRA_PRINTER_NAME
        if not messagebox.askyesno(
            "Calibrate Zebra Printer",
            (
                f"Run media calibration on {printer_name}?\n\n"
                "Make sure the correct labels are loaded. The printer may feed a few labels while it measures them."
            ),
        ):
            return False

        try:
            self._send_raw_printer_job("~JC", printer_name=printer_name, job_name="Zebra Calibration")
            log_event(
                LOGGER,
                logging.INFO,
                "printer_calibration_requested",
                printer_name=printer_name,
            )
            self._set_health_signal("printer", HEALTH_OK, f"Calibration sent: {printer_name}")
            self.printer_status_var.set(f"Printer Status: CALIBRATION SENT ({printer_name})")
            messagebox.showinfo(
                "Calibration Sent",
                "The Zebra calibration command was sent. The printer should now measure the labels currently loaded.",
            )
            return True
        except Exception as e:
            LOGGER.exception(
                structured_message(
                    "printer_calibration_failed",
                    printer_name=printer_name,
                    error=str(e),
                )
            )
            self._set_health_signal("printer", HEALTH_ERROR, "Calibration failed")
            messagebox.showerror("Calibration Failed", f"Could not calibrate the Zebra printer:\n{e}")
            return False

    def print_preview(self, zpl_code):
        """Print the previewed ZPL code"""
        started_at = time.perf_counter()
        print_job_id = make_correlation_id("print")
        printer_name = ""
        print_quantity = self._coerce_print_quantity()
        preset_name = self._selected_zpl_preset_name()
        try:
            # Get the default printer
            printer_name = win32print.GetDefaultPrinter()
            # Guard: do not send if printer appears disconnected/offline
            if not self._is_printer_available(printer_name):
                LOGGER.error(
                    structured_message(
                        "printer_preview_cancelled_printer_unavailable",
                        print_job_id=print_job_id,
                        printer_name=printer_name,
                        duration_ms=elapsed_ms(started_at),
                    )
                )
                self._set_health_signal("printer", HEALTH_WARNING, "Preview blocked; printer unavailable")
                self._record_print_audit(
                    job_type="Preview",
                    status="Preview",
                    quantity=print_quantity,
                    printer_name=printer_name,
                    preset_name=preset_name,
                    product_code=self.product_var.get() if self.__dict__.get("product_var") is not None else "",
                    workcenter=getattr(self, "current_workcenter", ""),
                    outcome="Failed",
                    error="Printer unavailable",
                )
                messagebox.showwarning("Printer Disconnected", "Default printer is offline/disconnected. Printing cancelled.")
                return False
            
            zpl_payload = self._prepare_zpl_print_job(zpl_code, print_quantity)
            print(f"Printing {print_quantity} label(s)")

            self._send_raw_printer_job(zpl_payload, printer_name=printer_name, job_name="ZPL Preview")
            print(f"Successfully queued {print_quantity} label(s) to printer")
            log_event(
                LOGGER,
                logging.INFO,
                "printer_preview_queued",
                print_job_id=print_job_id,
                printer_name=printer_name,
                quantity=print_quantity,
                duration_ms=elapsed_ms(started_at),
            )
            self._record_print_audit(
                job_type="Preview",
                status="Preview",
                quantity=print_quantity,
                printer_name=printer_name,
                preset_name=preset_name,
                product_code=self.product_var.get() if self.__dict__.get("product_var") is not None else "",
                workcenter=getattr(self, "current_workcenter", ""),
                outcome="Queued",
            )
            self._set_health_signal("printer", HEALTH_OK, f"Preview queued: {printer_name}")
            return True
            
        except Exception as e:
            messagebox.showerror("Print Error", f"Error sending to printer: {str(e)}")
            LOGGER.exception(
                structured_message(
                    "printer_preview_failed",
                    print_job_id=print_job_id,
                    printer_name=locals().get('printer_name', ''),
                    duration_ms=elapsed_ms(started_at),
                )
            )
            self._set_health_signal("printer", HEALTH_ERROR, "Preview print failed")
            self._record_print_audit(
                job_type="Preview",
                status="Preview",
                quantity=print_quantity,
                printer_name=printer_name,
                preset_name=preset_name,
                product_code=self.product_var.get() if self.__dict__.get("product_var") is not None else "",
                workcenter=getattr(self, "current_workcenter", ""),
                outcome="Failed",
                error=str(e),
            )
            return False
    
    def update_cycle_time(self):
        """Update the cycle time display based on production rate"""
        if hasattr(self, 'pcs_min_var') and self.pcs_min_var.get():
            try:
                pcs_per_min = float(self.pcs_min_var.get())
                if pcs_per_min > 0:
                    cycle_time_sec = 60.0 / pcs_per_min  # Convert pcs/min to sec/pc
                    self.cycle_time_var.set(f"{cycle_time_sec:.2f} s")
                    return
            except (ValueError, AttributeError):
                pass
        # Fallback to showing time since last scan if no valid production rate
        if hasattr(self, 'last_scan_time') and self.last_scan_time:
            current_time = datetime.now()
            cycle_time = (current_time - self.last_scan_time).total_seconds()
            self.cycle_time_var.set(f"{cycle_time:.2f} s")
    
    def print_label(
        self,
        barcode_text,
        description="N/A",
        Barc="N/A",
        PC="N/A",
        status=SCAN_STATUS_SCANNED,
        job_type="Label",
        update_last_context=True,
        scan_id="",
        print_job_id=None,
    ):
        started_at = time.perf_counter()
        print_job_id = print_job_id or make_correlation_id("print")
        printer_name = ZEBRA_PRINTER_NAME
        print_quantity = self._coerce_print_quantity()
        preset_name = self._selected_zpl_preset_name()
        product_code = self.product_var.get() if self.__dict__.get("product_var") is not None else ""
        workcenter = getattr(self, "current_workcenter", "")
        try:
            print(f"\n=== Starting print job for barcode: {barcode_text} ===")
            
            # Update the cycle time display
            self.update_cycle_time()
            
            # First try to use the selected ZPL preset from dropdown
            zpl_template = None
            preset_dimensions = None
            zpl_preset_var = self.__dict__.get('zpl_preset')
            if zpl_preset_var is not None and zpl_preset_var.get():
                selected_preset = zpl_preset_var.get().strip()
                preset_path = self._resolve_zpl_preset_path(selected_preset)
                if preset_path and os.path.exists(preset_path):
                    try:
                        with open(preset_path, 'r', encoding='utf-8') as f:
                            zpl_template = f.read()
                        preset_dimensions = self._apply_selected_zpl_preset_dimensions(selected_preset, zpl_template)
                        print(f"Using selected ZPL preset: {selected_preset} ({preset_path})")
                    except Exception as e:
                        print(f"Error loading selected ZPL preset: {str(e)}")
                        messagebox.showwarning("Warning", f"Error loading selected ZPL preset: {str(e)}\nTrying product-specific template...")
            
            # If no template from dropdown, try product-specific template
            current_product = self.__dict__.get('current_product')
            if not zpl_template and current_product:
                zpl_file = f"{current_product}.zpl"
                zpl_path = self.get_zpl_file_path(zpl_file)
                
                if zpl_path:
                    try:
                        with open(zpl_path, 'r', encoding='utf-8') as f:
                            zpl_template = f.read()
                        preset_name = zpl_file
                        print(f"Loaded ZPL template from: {zpl_path}")
                    except Exception as e:
                        print(f"Error loading ZPL template from {zpl_path}: {str(e)}")
                        messagebox.showwarning("Warning", f"Error loading ZPL template: {str(e)}\nUsing default template.")
                else:
                    print(f"ZPL template not found for product: {current_product}")
            
            # If no template was loaded, use the default template
            if not zpl_template:
                print("Using default ZPL template")
                preset_name = preset_name or "Default"
                zpl_template = """^XA
    ^PW{width_dots}
    ^LL{height_dots}
    ^CF0,30
    ^FO50,50^FD{description}^FS
    ^BY3,3,100
    ^FO50,100^BCN,100,Y,N,N^FD{barcode_text}^FS
    ^CF0,20
    ^FO50,200^FD{Barc}^FS
    ^FO50,230^FD{PC}^FS
    ^XZ"""
                
            # Always ensure we have the basic template structure
            if "^XA" not in zpl_template or "^XZ" not in zpl_template:
                zpl_template = f"^XA\n{zpl_template}\n^XZ"
                
            # Calculate dimensions
            dpi = 203
            width_mm = preset_dimensions[0] if preset_dimensions else LABEL_WIDTH
            height_mm = preset_dimensions[1] if preset_dimensions else LABEL_HEIGHT
            width_dots = int(width_mm * dpi / 25.4)
            height_dots = int(height_mm * dpi / 25.4)
            
            # Generate additional data
            batch_code = f"{barcode_text[:5]}{datetime.now().strftime('%d%m')}"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            print(f"Width: {width_dots} dots, Height: {height_dots} dots")
            print(f"Barcode text: {barcode_text}")
            print(f"Description: {description}")
            print(f"Barc: {Barc}, PC: {PC}")
            
            try:
                # Format the ZPL code with all available variables
                zpl = zpl_template.format(
                    width_dots=width_dots,
                    height_dots=height_dots,
                    barcode_text=barcode_text,
                    description=description,
                    Barc=Barc,
                    PC=PC,
                    batch_code=batch_code,
                    timestamp=timestamp,
                    desc1=description[:28],
                    desc2=description[29:] if len(description) > 29 else ""
                )
                
                # Ensure proper line endings
                zpl = zpl.replace('\r\n', '\n').replace('\r', '\n')
                
                print("ZPL code generated successfully")
                print(f"ZPL Preview (first 100 chars): {zpl[:100]}...")
                
            except Exception as e:
                error_msg = f"Error generating ZPL code: {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                raise Exception(error_msg)

            # Use the specific Zebra printer
            print(f"Attempting to print to: {printer_name}")
            
            if not self._is_printer_available(printer_name):
                error_msg = f"Zebra printer {printer_name} is not available"
                print(error_msg)
                LOGGER.error(
                    structured_message(
                        "print_label_cancelled_printer_unavailable",
                        scan_id=scan_id,
                        print_job_id=print_job_id,
                        printer_name=printer_name,
                        barcode=barcode_text,
                        duration_ms=elapsed_ms(started_at),
                    )
                )
                self._set_health_signal("printer", HEALTH_WARNING, f"Unavailable: {printer_name}")
                self._record_print_audit(
                    job_type=job_type,
                    barcode=barcode_text,
                    status=status,
                    quantity=print_quantity,
                    printer_name=printer_name,
                    preset_name=preset_name,
                    product_code=product_code,
                    workcenter=workcenter,
                    outcome="Failed",
                    error=error_msg,
                )
                messagebox.showwarning("Printer Disconnected", f"Zebra printer {printer_name} is offline/disconnected. Printing cancelled.")
                return False

            try:
                zpl_payload = self._prepare_zpl_print_job(zpl, print_quantity)
                print(f"Printing {print_quantity} label(s)")
                print("Opening printer connection...")
                self._send_raw_printer_job(zpl_payload, printer_name=printer_name, job_name="ZPL Label")
                print(f"Successfully queued {print_quantity} label(s) to printer")
                log_event(
                    LOGGER,
                    logging.INFO,
                    "print_label_queued",
                    scan_id=scan_id,
                    print_job_id=print_job_id,
                    printer_name=printer_name,
                    barcode=barcode_text,
                    quantity=print_quantity,
                    duration_ms=elapsed_ms(started_at),
                )
                self._record_print_audit(
                    job_type=job_type,
                    barcode=barcode_text,
                    status=status,
                    quantity=print_quantity,
                    printer_name=printer_name,
                    preset_name=preset_name,
                    product_code=product_code,
                    workcenter=workcenter,
                    outcome="Queued",
                )
                self._set_health_signal("printer", HEALTH_OK, f"Label queued: {printer_name}")
                if update_last_context:
                    self.last_label_context = {
                        "barcode_text": barcode_text,
                        "description": description,
                        "Barc": Barc,
                        "PC": PC,
                        "status": status,
                        "scan_id": scan_id,
                        "print_job_id": print_job_id,
                    }
                return True
                
            except Exception as e:
                error_msg = f"Error during printing: {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                LOGGER.exception(
                    structured_message(
                        "print_label_failed",
                        scan_id=scan_id,
                        print_job_id=print_job_id,
                        printer_name=printer_name,
                        barcode=barcode_text,
                        duration_ms=elapsed_ms(started_at),
                    )
                )
                self._set_health_signal("printer", HEALTH_ERROR, "Label print failed")
                self._record_print_audit(
                    job_type=job_type,
                    barcode=barcode_text,
                    status=status,
                    quantity=print_quantity,
                    printer_name=printer_name,
                    preset_name=preset_name,
                    product_code=product_code,
                    workcenter=workcenter,
                    outcome="Failed",
                    error=str(e),
                )
                messagebox.showerror("Printer Error", error_msg)
                return False

        except Exception as e:
            error_msg = f"Unexpected error in print_label: {str(e)}"
            print(error_msg)
            print(traceback.format_exc())
            LOGGER.exception(
                structured_message(
                    "print_label_unexpected_failure",
                    barcode=barcode_text,
                    scan_id=scan_id,
                    print_job_id=print_job_id,
                    duration_ms=elapsed_ms(started_at),
                )
            )
            self._set_health_signal("printer", HEALTH_ERROR, "Label print failed")
            self._record_print_audit(
                job_type=job_type,
                barcode=barcode_text,
                status=status,
                quantity=print_quantity,
                printer_name=printer_name,
                preset_name=preset_name,
                product_code=product_code,
                workcenter=workcenter,
                outcome="Failed",
                error=str(e),
            )
            messagebox.showerror("Error", error_msg)
            return False

if __name__ == '__main__':
    import traceback
    import sys
    import os

    log_dir = os.path.join(BASE_PATH, 'logs')
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('gspread').setLevel(logging.INFO)
    
    def log_uncaught_exceptions(exc_type, exc_value, exc_traceback):
        """Log uncaught exceptions with full traceback"""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
            
        LOGGER.critical(
            structured_message("uncaught_exception"),
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # Show user-friendly error message
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                "Application Error",
                f"An unexpected error occurred.\n\n{str(exc_value)}\n\n"
                f"Check logs in: {log_dir}"
            )
        except Exception as show_error:
            LOGGER.error(f"Failed to show error dialog: {str(show_error)}", exc_info=True)
    
    # Set global exception handler
    sys.excepthook = log_uncaught_exceptions
    
    # Log application startup
    log_event(LOGGER, logging.INFO, "app_entrypoint_start", python_version=sys.version, working_directory=os.getcwd(), log_dir=log_dir)
    error_occurred = False
    error_message = "An unknown error occurred"
    
    try:
        app = BarcodeApp()
        log_event(LOGGER, logging.INFO, "app_mainloop_start")
        app.mainloop()
        log_event(LOGGER, logging.INFO, "app_mainloop_exit")
    except Exception as e:
        error_occurred = True
        error_message = str(e)
        LOGGER.exception(structured_message("app_mainloop_failed", error_message=error_message))
    finally:
        # Ensure all logs are flushed
        logging.shutdown()
        
        # Only show error dialog if an error occurred
        if error_occurred:
            # Try to show error in message box if possible
            try:
                import tkinter.messagebox as messagebox
                messagebox.showerror(
                    "Fatal Error", 
                    f"The application encountered a fatal error and must close.\n\n{error_message}\n\nCheck app_errors.log for details."
                )
            except Exception as log_error:
                print(f"Failed to show error dialog: {log_error}", file=sys.stderr)
