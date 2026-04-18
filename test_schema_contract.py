from __future__ import annotations

import unittest

from schema_contract import normalize_scan_row, normalize_scan_status


class SchemaContractTests(unittest.TestCase):
    def test_normalize_scan_status_treats_unknown_as_scanned(self) -> None:
        self.assertEqual(normalize_scan_status("UNKNOWN", is_rework=False), "Scanned")

    def test_normalize_scan_status_keeps_rework_aliases(self) -> None:
        self.assertEqual(normalize_scan_status("rework", is_rework=False), "Reworked")

    def test_normalize_scan_row_converts_unknown_status_to_canonical_value(self) -> None:
        row = normalize_scan_row(
            {
                "Timestamp": "2026-04-14 07:30:00",
                "Product Code": "P-100",
                "Barcode": "ABC123",
                "Batch": "BATCH1",
                "Cycle time": "12.50",
                "Status": "UNKNOWN",
                "Description": "Pump",
                "Operator": "Operator",
                "Notes": "",
                "Is_Rework": False,
                "Workcenter": "Q-PP",
            }
        )

        self.assertEqual(row["Status"], "Scanned")
        self.assertFalse(row["Is_Rework"])


if __name__ == "__main__":
    unittest.main()
