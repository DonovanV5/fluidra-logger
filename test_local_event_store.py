from __future__ import annotations

from contextlib import closing
import os
import tempfile
import unittest

from local_event_store import LocalEventStore
from schema_contract import (
    build_downtime_row,
    build_production_row,
    build_scan_row,
    PRODUCTION_EVENT_END,
)
from datetime import datetime


class LocalEventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "events.sqlite3")
        self.store = LocalEventStore(self.db_path)
        self.now = datetime(2026, 4, 10, 7, 30, 0)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scan_commit_and_duplicate_lookup(self) -> None:
        row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="ABC123",
            batch="BATCH1",
            cycle_time_seconds=12.5,
            status="Scanned",
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )

        event_id, inserted = self.store.append_scan_event(row, normalized_barcode="ABC123")

        self.assertTrue(inserted)
        self.assertTrue(event_id)
        self.assertTrue(self.store.scan_exists("ABC123"))
        self.assertIn("ABC123", self.store.load_known_barcodes())

    def test_duplicate_scan_commit_returns_existing_event_without_second_insert(self) -> None:
        row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="ABC123",
            batch="BATCH1",
            cycle_time_seconds=12.5,
            status="Scanned",
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )

        first_event_id, first_inserted = self.store.append_scan_event(row, normalized_barcode="ABC123")
        second_event_id, second_inserted = self.store.append_scan_event(row, normalized_barcode="ABC123")

        self.assertTrue(first_inserted)
        self.assertFalse(second_inserted)
        self.assertEqual(first_event_id, second_event_id)
        self.assertEqual(len(self.store.fetch_scan_rows()), 1)

    def test_bootstrap_scan_rows_are_marked_synced(self) -> None:
        row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="ABC123",
            batch="BATCH1",
            cycle_time_seconds=12.5,
            status="Scanned",
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )

        self.store.append_scan_event(row, normalized_barcode="ABC123", bootstrap_synced=True)

        self.assertEqual(self.store.fetch_pending_scan_google_events(), [])

    def test_production_and_downtime_events_track_pending_sync(self) -> None:
        production_row = build_production_row(
            timestamp=self.now,
            event_type=PRODUCTION_EVENT_END,
            product_code="P-100",
            duration_seconds=3600,
            production_count=10,
            operator="Operator",
            workcenter="Q-PP",
        )
        downtime_row = build_downtime_row(
            timestamp=self.now,
            duration_seconds=300,
            reason="Mechanical",
            description="Adjustment",
            operator="Operator",
            workcenter="Q-PP",
        )

        prod_id, prod_inserted = self.store.append_production_event(production_row)
        dt_id, dt_inserted = self.store.append_downtime_event(downtime_row)

        self.assertTrue(prod_inserted)
        self.assertTrue(dt_inserted)
        self.assertEqual(len(self.store.fetch_pending_production_google_events()), 1)
        self.assertEqual(len(self.store.fetch_pending_downtime_google_events()), 1)

        self.store.mark_production_google_synced(prod_id)
        self.store.mark_downtime_google_synced(dt_id)

        self.assertEqual(self.store.fetch_pending_production_google_events(), [])
        self.assertEqual(self.store.fetch_pending_downtime_google_events(), [])

    def test_rework_scan_and_production_start_are_stored_with_canonical_values(self) -> None:
        rework_row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="RWK123",
            batch="BATCH1",
            cycle_time_seconds=6.5,
            status="Reworked",
            description="Pump",
            operator="Operator",
            notes="Rework",
            is_rework=True,
            workcenter="Q-PP",
        )
        production_start_row = build_production_row(
            timestamp=self.now,
            event_type="invalid",
            product_code="P-100",
            duration_seconds=0,
            production_count=0,
            operator="Operator",
            workcenter="Q-PP",
        )

        self.store.append_scan_event(rework_row, normalized_barcode="RWK123")
        self.store.append_production_event(production_start_row)

        stored_scan = self.store.fetch_scan_rows()[0]
        stored_production = self.store.fetch_production_rows()[0]

        self.assertEqual(stored_scan["Status"], "Reworked")
        self.assertTrue(stored_scan["Is_Rework"])
        self.assertEqual(stored_production["Event Type"], "PRODUCTION_START")

    def test_scan_google_sync_state_tracks_attempts_and_row_ref(self) -> None:
        row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="ABC123",
            batch="BATCH1",
            cycle_time_seconds=12.5,
            status="Scanned",
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )

        event_id, inserted = self.store.append_scan_event(row, normalized_barcode="ABC123")

        self.assertTrue(inserted)

        self.store.mark_scan_google_failed(event_id, "scans", "network down")
        self.store.mark_scan_google_synced(event_id, "scans", row_ref="Scans!12")

        with closing(self.store._connect()) as conn:
            db_row = conn.execute(
                """
                SELECT google_scans_synced, google_scans_state, google_scans_attempts,
                       google_scans_last_error, google_scans_last_attempted_at, google_scans_row_ref
                FROM scan_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        self.assertEqual(db_row["google_scans_synced"], 1)
        self.assertEqual(db_row["google_scans_state"], "synced")
        self.assertEqual(db_row["google_scans_attempts"], 2)
        self.assertEqual(db_row["google_scans_last_error"], None)
        self.assertTrue(db_row["google_scans_last_attempted_at"])
        self.assertEqual(db_row["google_scans_row_ref"], "Scans!12")

    def test_google_sync_summary_counts_pending_and_failed_sinks(self) -> None:
        scan_row = build_scan_row(
            timestamp=self.now,
            product_code="P-100",
            barcode="ABC123",
            batch="BATCH1",
            cycle_time_seconds=12.5,
            status="Scanned",
            description="Pump",
            operator="Operator",
            notes="",
            is_rework=False,
            workcenter="Q-PP",
        )
        production_row = build_production_row(
            timestamp=self.now,
            event_type=PRODUCTION_EVENT_END,
            product_code="P-100",
            duration_seconds=3600,
            production_count=10,
            operator="Operator",
            workcenter="Q-PP",
        )

        scan_id, _ = self.store.append_scan_event(scan_row, normalized_barcode="ABC123")
        production_id, _ = self.store.append_production_event(production_row)

        self.store.mark_scan_google_failed(scan_id, "scans", "network down")
        self.store.mark_production_google_failed(production_id, "network down")

        summary = self.store.get_google_sync_summary()

        self.assertEqual(summary["scan_scans_pending"], 1)
        self.assertEqual(summary["scan_scans_failed"], 1)
        self.assertEqual(summary["scan_sheet1_pending"], 1)
        self.assertEqual(summary["production_pending"], 1)
        self.assertEqual(summary["production_failed"], 1)
        self.assertEqual(summary["failed_total"], 2)
        self.assertEqual(summary["pending_total"], 3)


if __name__ == "__main__":
    unittest.main()
