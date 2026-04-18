from __future__ import annotations

import importlib.util
import csv
import threading
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main, mock


class ValueVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeWorksheet:
    title = "Products"
    row_count = 100
    col_count = 20

    def get_all_values(self):
        return [
            ["Product Code", "Description", "", "", "Expected Cycle", "", "", "", "Barcode Display"],
            ["P-100", "Pump", "", "", "10", "", "", "", "BARC-100"],
        ]


class FakeWorkbook:
    def __init__(self):
        self.products = FakeWorksheet()
        self.downtime = FakeWorksheet()
        self.downtime.title = "Downtime"

    def worksheet(self, title):
        if title == "Products":
            return self.products
        if title == "Downtime":
            return self.downtime
        raise KeyError(title)

    def worksheets(self):
        return [self.products, self.downtime]


class FakeClient:
    def open(self, name):
        return FakeWorkbook()


def load_app_module():
    source_path = Path(__file__).with_name("Fluidra_Manufacturing_Solutionv7.4.py")
    spec = importlib.util.spec_from_file_location("fms_app_under_test", source_path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch(
        "oauth2client.service_account.ServiceAccountCredentials.from_json_keyfile_name",
        return_value=object(),
    ), mock.patch("gspread.authorize", return_value=FakeClient()):
        spec.loader.exec_module(module)
        module.initialize_google_sheets()
    module.BarcodeApp.__del__ = lambda self: None
    return module


def make_app(module):
    app = module.BarcodeApp.__new__(module.BarcodeApp)
    app._scan_processing = False
    app._active_scan_barcode = None
    app._pending_scan_after_id = None
    app._scan_capture_after_id = None
    app._scan_focus_after_id = None
    app._scan_capture_buffer = ""
    app._scan_capture_last_key_at = 0.0
    app._scanner_capture_installed = False
    app._barcode_trace_suppressed = False
    app._shutdown_requested = False
    app.production_running = True
    app.production_count = 0
    app.start_time = None
    app.last_scan_time = None
    app.total_runtime_seconds = 0
    app.current_workcenter = "Q-PP"
    app.logging_backend = "Google Sheets"
    app.server_csv_dir = ""
    app._server_csv_lock = threading.Lock()
    app.print_quantity = 2
    app._saved_zpl_preset = ""
    app.print_quantity_var = ValueVar("2")
    app.product_var = ValueVar("P-100")
    app.barcode_var = ValueVar("")
    app.last_scanned_var = ValueVar("")
    app.production_count_var = ValueVar("0")
    app.description_var = ValueVar("")
    app.PC_var = ValueVar("")
    app.cycle_time_var = ValueVar("")
    app.pcs_min_var = ValueVar("0.00")
    app.operator_name_var = ValueVar("Operator")
    app.teraoka_enabled = ValueVar(False)
    app.health_signals = {}
    app.last_successful_server_csv_write_at = None
    app._barcode_cache = set()
    app._barcode_cache_lock = threading.Lock()
    app._barcode_cache_last_update = 0
    app._last_barcode_check = None
    app._last_barcode_result = False
    app._refresh_health_display = lambda: None
    app._set_health_signal = lambda *args, **kwargs: None
    app._set_health_timestamp = lambda *args, **kwargs: None
    app._queue_ui_task = lambda *args, **kwargs: None
    app._is_ui_thread = lambda: True
    app.after = lambda delay, callback=None, *args: "after-id"
    app.after_cancel = lambda after_id: None
    app.grab_current = lambda: None
    app.focus_get = lambda: None
    app.lift = lambda: None
    app.focus_force = lambda: None
    app.is_duplicate_barcode = lambda barcode: False
    return app


class ScanPrintFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_app_module()

    def test_prepare_zpl_print_job_uses_configured_quantity_once(self):
        app = self.module.BarcodeApp.__new__(self.module.BarcodeApp)

        payload = app._prepare_zpl_print_job('^XA\n^FO1,1^FDTEST^FS\n^XZ\n"""', 2)

        self.assertIn("^PQ2", payload)
        self.assertEqual(payload.count("^PQ2"), 1)
        self.assertNotIn('"""', payload)

    def test_sync_event_header_expands_sheet_before_update_cell(self):
        app = make_app(self.module)

        class ExpandableWorksheet:
            title = "Scans"
            row_count = 10
            col_count = 11

            def __init__(self):
                self.added_cols = 0
                self.updated = []

            def add_cols(self, count):
                self.added_cols += count
                self.col_count += count

            def add_rows(self, count):
                self.row_count += count

            def update_cell(self, row, col, value):
                self.updated.append((row, col, value))

        ws = ExpandableWorksheet()

        headers, sync_col = app._ensure_sync_event_id_column(
            ws,
            "Scans",
            list(self.module.SCAN_HEADERS),
            self.module.SCAN_HEADERS,
        )

        self.assertEqual(sync_col, 12)
        self.assertEqual(ws.added_cols, 1)
        self.assertEqual(ws.updated, [(1, 12, self.module.SYNC_EVENT_ID_HEADER)])
        self.assertEqual(headers[-1], self.module.SYNC_EVENT_ID_HEADER)

    def test_product_picker_records_and_selection_update_product_var(self):
        app = make_app(self.module)
        updates = []
        app.update_description_on_select = lambda value=None: updates.append(app.product_var.get())
        app.barcode_entry = mock.Mock()

        records = app._load_product_records()
        app._select_product(records[0]["code"])

        self.assertEqual(records[0]["code"], "P-100")
        self.assertEqual(app.product_options, ["P-100"])
        self.assertEqual(app.product_var.get(), "P-100")
        self.assertEqual(updates, ["P-100"])
        app.barcode_entry.focus_set.assert_called_once()

    def test_global_scanner_capture_logs_scan_when_focus_is_not_textbox(self):
        app = make_app(self.module)
        focused_button = mock.Mock()
        app.focus_get = lambda: focused_button
        app.barcode_entry = mock.Mock()
        app.barcode_entry.cget.return_value = "normal"
        log_requests = []
        print_requests = []
        app.log_scan_to_excel = lambda barcode, **kwargs: log_requests.append((barcode, kwargs)) or True
        app.print_label = lambda **kwargs: print_requests.append(kwargs) or True

        with mock.patch.object(
            self.module,
            "get_product_info",
            return_value={"description": "Pump", "Barc": "BARC-100", "PC": "P-100"},
        ):
            for char in "ABC123":
                result = app._on_global_scan_keypress(SimpleNamespace(keysym=char, char=char))
                self.assertEqual(result, "break")
            result = app._on_global_scan_keypress(SimpleNamespace(keysym="Return", char="\r"))

        self.assertEqual(result, "break")
        self.assertEqual(app.production_count, 1)
        self.assertEqual(log_requests[0][0], "ABC123")
        self.assertEqual(print_requests[0]["barcode_text"], "ABC123")

    def test_global_scanner_capture_ignores_operator_text_fields(self):
        app = make_app(self.module)
        app.barcode_entry = mock.Mock()
        app.barcode_entry.cget.return_value = "normal"

        class FocusedEntry:
            def winfo_class(self):
                return "Entry"

        app.focus_get = lambda: FocusedEntry()

        result = app._on_global_scan_keypress(SimpleNamespace(keysym="A", char="A"))

        self.assertIsNone(result)
        self.assertEqual(app._scan_capture_buffer, "")

    def test_forced_scan_focus_targets_inner_barcode_entry_and_retries(self):
        app = make_app(self.module)
        inner_entry = mock.Mock()
        app.barcode_entry = mock.Mock()
        app.barcode_entry._entry = inner_entry
        app.barcode_entry.cget.return_value = "normal"
        app.after = mock.Mock(return_value="after-id")

        focused = app._refocus_scan_entry(force=True, attempts=2)

        self.assertTrue(focused)
        inner_entry.focus_force.assert_called_once()
        inner_entry.icursor.assert_called_once_with("end")
        app.after.assert_called_once()

    def test_print_label_sends_single_payload_with_configured_quantity(self):
        app = make_app(self.module)
        app.update_cycle_time = lambda: None
        app._is_printer_available = lambda printer_name: True
        payloads = []
        audits = []
        app._send_raw_printer_job = lambda payload, printer_name=None, job_name="": payloads.append(payload)
        app._record_print_audit = lambda **record: audits.append(record)

        ok = app.print_label(
            "ABC123",
            description="Pump",
            Barc="BARC-100",
            PC="P-100",
            scan_id="scan_test",
            print_job_id="print_test",
        )

        self.assertTrue(ok)
        self.assertEqual(len(payloads), 1)
        self.assertIn("^PQ2", payloads[0])
        self.assertEqual(audits[-1]["outcome"], "Queued")
        self.assertNotIn("scan_id", audits[-1])
        self.assertNotIn("print_job_id", audits[-1])
        self.assertEqual(app.last_label_context["scan_id"], "scan_test")
        self.assertEqual(app.last_label_context["print_job_id"], "print_test")

    def test_normal_scan_logs_and_prints(self):
        app = make_app(self.module)
        log_requests = []
        print_requests = []
        app.log_scan_to_excel = lambda barcode, **kwargs: log_requests.append((barcode, kwargs)) or True
        app.print_label = lambda **kwargs: print_requests.append(kwargs) or True

        with mock.patch.object(
            self.module,
            "get_product_info",
            return_value={"description": "Pump", "Barc": "BARC-100", "PC": "P-100"},
        ):
            accepted = app.handle_scan(None, barcode_override="ABC123")

        self.assertTrue(accepted)
        self.assertEqual(app.production_count, 1)
        self.assertEqual(log_requests[0][1]["status"], "Scanned")
        self.assertRegex(log_requests[0][1]["scan_id"], r"^scan_\d{14}_[0-9a-f]{8}$")
        self.assertEqual(print_requests[0]["status"], "Scanned")
        self.assertEqual(print_requests[0]["scan_id"], log_requests[0][1]["scan_id"])

    def test_duplicate_scan_routes_to_popup_without_printing(self):
        app = make_app(self.module)
        routed = []
        app.is_duplicate_barcode = lambda barcode: True
        app.handle_duplicate_barcode = lambda barcode: routed.append(barcode)
        app.log_scan_to_excel = lambda *args, **kwargs: self.fail("Duplicate scan should not log immediately")
        app.print_label = lambda *args, **kwargs: self.fail("Duplicate scan should not print immediately")

        accepted = app.handle_scan(None, barcode_override="ABC123")

        self.assertFalse(accepted)
        self.assertEqual(routed, ["ABC123"])

    def test_rework_button_path_logs_rework_and_prints_once(self):
        app = make_app(self.module)
        log_requests = []
        print_requests = []
        app.log_scan_to_excel = lambda barcode, **kwargs: log_requests.append((barcode, kwargs)) or True
        app.print_label = lambda **kwargs: print_requests.append(kwargs) or True
        state = {"started": False}

        with mock.patch.object(
            self.module,
            "get_product_info",
            return_value={"description": "Pump", "Barc": "BARC-100", "PC": "P-100"},
        ):
            first = app._submit_duplicate_rework_scan("ABC123", "Rework note", submission_state=state)
            second = app._submit_duplicate_rework_scan("ABC123", "Rework note", submission_state=state)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(app.production_count, 0)
        self.assertEqual(log_requests[0][1]["status"], "Reworked")
        self.assertEqual(print_requests[0]["status"], "Reworked")
        self.assertEqual(len(print_requests), 1)

    def test_auto_downtime_multiplier_is_configurable(self):
        app = make_app(self.module)

        app._set_auto_downtime_multiplier("3.25")

        self.assertEqual(app.auto_downtime_multiplier, 3.25)
        self.assertEqual(app._get_auto_downtime_multiplier(), 3.25)
        with self.assertRaises(ValueError):
            app._set_auto_downtime_multiplier("0.5")

    def test_auto_downtime_uses_configured_multiplier(self):
        app = make_app(self.module)
        app.expected_cycle = 10
        app.production_running = True
        app.in_auto_downtime = False
        app._active_planned_break_context = None
        app._get_active_planned_break_window = lambda now: None
        app._finalize_planned_break_context = lambda now: None
        app.start_downtime_popup = mock.Mock()
        app.after = lambda delay, callback=None, *args: None
        app._set_auto_downtime_multiplier("3")

        app.last_scan_time = datetime.now() - timedelta(seconds=26)
        app.check_auto_downtime()
        app.start_downtime_popup.assert_not_called()

        app.last_scan_time = datetime.now() - timedelta(seconds=31)
        app.check_auto_downtime()
        app.start_downtime_popup.assert_called_once()

    def test_diagnostics_redaction_masks_sensitive_values(self):
        app = make_app(self.module)

        redacted = app._redact_diagnostics_data(
            {
                "admin_password": "secret",
                "api_key": "abc",
                "nested": [{"token": "hidden", "workcenter": "Q-PP"}],
                "safe": "visible",
            }
        )

        self.assertEqual(redacted["admin_password"], "***REDACTED***")
        self.assertEqual(redacted["api_key"], "***REDACTED***")
        self.assertEqual(redacted["nested"][0]["token"], "***REDACTED***")
        self.assertEqual(redacted["nested"][0]["workcenter"], "Q-PP")
        self.assertEqual(redacted["safe"], "visible")

    def test_server_csv_sync_writes_dashboard_headers_under_workcenter_station(self):
        app = make_app(self.module)
        app.logging_backend = self.module.LOG_BACKEND_SERVER_CSV
        scan_row = self.module.build_scan_row(
            timestamp=datetime(2026, 4, 17, 8, 0, 0),
            product_code="P-100",
            barcode="ABC123",
            batch="ABC1704",
            cycle_time_seconds=12.3,
            status=self.module.SCAN_STATUS_SCANNED,
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )
        production_row = self.module.build_production_row(
            timestamp=datetime(2026, 4, 17, 8, 0, 0),
            event_type=self.module.PRODUCTION_EVENT_START,
            product_code="P-100",
            duration_seconds=0,
            production_count=0,
            operator="Operator",
            workcenter="Q-PP",
        )
        downtime_row = self.module.build_downtime_row(
            timestamp=datetime(2026, 4, 17, 9, 0, 0),
            duration_seconds=60,
            reason="Test",
            description="",
            operator="Operator",
            workcenter="Q-PP",
        )
        app.local_store = SimpleNamespace(
            fetch_scan_rows=lambda: [scan_row],
            fetch_production_rows=lambda: [production_row],
            fetch_downtime_rows=lambda: [downtime_row],
        )

        with TemporaryDirectory() as tmp:
            app.server_csv_dir = tmp
            ok = app._sync_local_store_to_server_csv()
            scan_path = Path(tmp) / "Q-PP" / self.module.APP_HOSTNAME / "scans.csv"

            self.assertTrue(ok)
            self.assertTrue(scan_path.exists())
            with scan_path.open("r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, self.module.SCAN_HEADERS)
            self.assertEqual(rows[0]["Barcode"], "ABC123")

    def test_server_csv_product_lookup_reads_products_file(self):
        app = make_app(self.module)
        app.logging_backend = self.module.LOG_BACKEND_SERVER_CSV

        with TemporaryDirectory() as tmp:
            app.server_csv_dir = tmp
            products_path = Path(tmp) / "products.csv"
            with products_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Product Code", "Description", "Expected Cycle", "Barcode Display"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Product Code": "P-200",
                        "Description": "Server Pump",
                        "Expected Cycle": "15",
                        "Barcode Display": "BARC-200",
                    }
                )

            product_info = app.get_product_info_from_sources("P-200")

        self.assertEqual(product_info["description"], "Server Pump")
        self.assertEqual(product_info["Barc"], "BARC-200")
        self.assertEqual(product_info["Expected_Cycle"], "15.00 sec")

    def test_server_csv_initialise_creates_structure_and_seeds_products(self):
        app = make_app(self.module)
        app.logging_backend = self.module.LOG_BACKEND_SERVER_CSV

        with TemporaryDirectory() as tmp:
            app.server_csv_dir = tmp
            ok = app.test_server_csv_directory(show_dialog=False)
            station_dir = Path(tmp) / "Q-PP" / self.module.APP_HOSTNAME
            products_path = Path(tmp) / "products.csv"

            self.assertTrue(ok)
            self.assertTrue((station_dir / "scans.csv").exists())
            self.assertTrue((station_dir / "production.csv").exists())
            self.assertTrue((station_dir / "downtime.csv").exists())
            self.assertTrue(products_path.exists())

            with products_path.open("r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        self.assertEqual(reader.fieldnames, self.module.SERVER_PRODUCT_HEADERS)
        self.assertEqual(rows[0]["Product Code"], "P-100")
        self.assertEqual(rows[0]["Expected Cycle"], "10")

    def test_server_csv_barcode_loader_reads_nested_station_files(self):
        app = make_app(self.module)
        app.logging_backend = self.module.LOG_BACKEND_SERVER_CSV

        with TemporaryDirectory() as tmp:
            app.server_csv_dir = tmp
            scan_dir = Path(tmp) / "Q-PP" / "Station-1"
            scan_dir.mkdir(parents=True)
            scan_path = scan_dir / "scans.csv"
            with scan_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.module.SCAN_HEADERS)
                writer.writeheader()
                writer.writerow({"Timestamp": "2026-04-17 08:00:00", "Barcode": "abc123"})

            barcodes = app._load_server_csv_barcodes(today_only=False)

        self.assertIn("ABC123", barcodes)

    def test_dashboard_facing_contract_headers_stay_stable(self):
        self.assertEqual(
            self.module.SCAN_HEADERS,
            [
                "Timestamp",
                "Product Code",
                "Barcode",
                "Batch",
                "Cycle time",
                "Status",
                "Description",
                "Operator",
                "Notes",
                "Is_Rework",
                "Workcenter",
            ],
        )
        self.assertEqual(
            self.module.PRINT_AUDIT_HEADERS,
            [
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
            ],
        )


if __name__ == "__main__":
    main()
