from __future__ import annotations

import os
import tempfile
import unittest

from fms_logging import HEALTH_ERROR, HEALTH_OK, HEALTH_UNKNOWN, HEALTH_WARNING
from startup_self_checks import (
    check_directory,
    check_google_workbook_access,
    check_optional_json_file,
    check_printer_target,
    check_required_file,
    check_sqlite_target,
    check_teraoka_readiness,
    summarize_startup_checks,
)


class _FakeWorksheet:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeWorkbook:
    def __init__(self, titles: list[str]) -> None:
        self._titles = titles

    def worksheets(self) -> list[_FakeWorksheet]:
        return [_FakeWorksheet(title) for title in self._titles]


class StartupSelfChecksTests(unittest.TestCase):
    def test_check_directory_creates_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "data")

            result = check_directory(target, "Local data directory", create_if_missing=True)

            self.assertEqual(result.state, HEALTH_OK)
            self.assertTrue(os.path.isdir(target))

    def test_required_file_missing_is_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = os.path.join(temp_dir, "missing.json")

            result = check_required_file(
                missing,
                "Google credentials",
                guidance="Restore the service-account JSON before startup.",
            )

            self.assertEqual(result.state, HEALTH_ERROR)
            self.assertIn("Restore the service-account JSON", result.detail)

    def test_optional_json_file_missing_is_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = os.path.join(temp_dir, "user_prefs.json")

            result = check_optional_json_file(
                missing,
                "User preferences",
                missing_detail="User preferences file not created yet; defaults are active.",
            )

            self.assertEqual(result.state, HEALTH_OK)

    def test_sqlite_target_check_opens_database_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "data", "events.sqlite3")

            result = check_sqlite_target(db_path)

            self.assertEqual(result.state, HEALTH_OK)
            self.assertTrue(os.path.exists(db_path))

    def test_google_workbook_access_reports_missing_required_sheet(self) -> None:
        workbook = _FakeWorkbook(["Products"])

        result = check_google_workbook_access(
            workbook,
            workbook_name="Production Log",
            required_sheets=["Products", "Downtime"],
            on_demand_sheets=["Scans", "Sheet1"],
        )

        self.assertEqual(result.state, HEALTH_ERROR)
        self.assertIn("missing required sheets", result.detail)

    def test_printer_target_warns_when_configured_printer_missing(self) -> None:
        result = check_printer_target("ZDesigner ZD220-203dpi ZPL", ["Office Printer"])

        self.assertEqual(result.state, HEALTH_WARNING)
        self.assertIn("Verify the Windows printer mapping", result.detail)

    def test_teraoka_readiness_disabled_is_unknown(self) -> None:
        result = check_teraoka_readiness(
            enabled=False,
            config_path="C:\\temp\\teraoka.json",
            wsdl_url="http://example/wsdl",
            supervisor="1019",
            workcenter="Q-PP",
        )

        self.assertEqual(result.state, HEALTH_UNKNOWN)

    def test_summarize_startup_checks_counts_states(self) -> None:
        summary = summarize_startup_checks(
            [
                check_printer_target("Configured", ["Configured"]),
                check_printer_target("Configured", []),
                check_teraoka_readiness(
                    enabled=False,
                    config_path="C:\\temp\\teraoka.json",
                    wsdl_url="http://example/wsdl",
                    supervisor="1019",
                    workcenter="Q-PP",
                ),
            ]
        )

        self.assertEqual(summary[HEALTH_OK], 1)
        self.assertEqual(summary[HEALTH_WARNING], 1)
        self.assertEqual(summary[HEALTH_UNKNOWN], 1)


if __name__ == "__main__":
    unittest.main()
