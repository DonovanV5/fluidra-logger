from __future__ import annotations

import json
import logging
import time
from unittest import TestCase, main

from fms_logging import (
    clear_log_context,
    elapsed_ms,
    log_timing,
    make_correlation_id,
    set_log_context,
    structured_message,
)


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class FmsLoggingTests(TestCase):
    def setUp(self):
        clear_log_context()

    def tearDown(self):
        clear_log_context()

    def test_structured_message_includes_global_context_without_overwriting_fields(self):
        set_log_context(app_run_id="run_1", host="station-1", workcenter="Q-PP")

        payload = json.loads(structured_message("scan_lifecycle_begin", barcode="ABC123", workcenter="Q-TEST"))

        self.assertEqual(payload["event"], "scan_lifecycle_begin")
        self.assertEqual(payload["app_run_id"], "run_1")
        self.assertEqual(payload["host"], "station-1")
        self.assertEqual(payload["workcenter"], "Q-TEST")
        self.assertEqual(payload["barcode"], "ABC123")

    def test_correlation_ids_are_prefixed_and_unique(self):
        first = make_correlation_id("Scan Job")
        second = make_correlation_id("Scan Job")

        self.assertRegex(first, r"^scanjob_\d{14}_[0-9a-f]{8}$")
        self.assertRegex(second, r"^scanjob_\d{14}_[0-9a-f]{8}$")
        self.assertNotEqual(first, second)

    def test_log_timing_records_duration_when_threshold_is_met(self):
        logger = logging.getLogger("fms_logging_test")
        logger.handlers = []
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = ListHandler()
        logger.addHandler(handler)
        start = time.perf_counter() - 0.01

        duration = log_timing(logger, logging.DEBUG, "operation_timing", start, min_duration_ms=0, outcome="ok")

        self.assertGreaterEqual(duration, 0)
        self.assertEqual(len(handler.records), 1)
        payload = json.loads(handler.records[0].getMessage())
        self.assertEqual(payload["event"], "operation_timing")
        self.assertEqual(payload["outcome"], "ok")
        self.assertIn("duration_ms", payload)

    def test_elapsed_ms_returns_milliseconds(self):
        start = time.perf_counter() - 0.005

        self.assertGreaterEqual(elapsed_ms(start), 0)


if __name__ == "__main__":
    main()
