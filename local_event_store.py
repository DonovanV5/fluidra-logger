from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any

from schema_contract import (
    DOWNTIME_HEADERS,
    PRODUCTION_HEADERS,
    SCAN_HEADERS,
    format_contract_timestamp,
    normalize_scan_row,
)

SYNC_STATE_PENDING = "pending"
SYNC_STATE_SYNCED = "synced"
SYNC_STATE_FAILED = "failed"


def _now_text() -> str:
    return format_contract_timestamp(datetime.now())


class LocalEventStore:
    """Local durable event store for logger transactions.

    SQLite writes are the authoritative local commit boundary. Downstream Google
    Sheets and Excel updates are tracked separately so they can be retried later.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = self._table_columns(conn, table)
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _initialize_sync_state_columns(self, conn: sqlite3.Connection) -> None:
        self._ensure_columns(
            conn,
            "scan_events",
            {
                "google_scans_state": f"TEXT NOT NULL DEFAULT '{SYNC_STATE_PENDING}'",
                "google_scans_last_attempted_at": "TEXT",
                "google_scans_row_ref": "TEXT",
                "google_sheet1_state": f"TEXT NOT NULL DEFAULT '{SYNC_STATE_PENDING}'",
                "google_sheet1_last_attempted_at": "TEXT",
                "google_sheet1_row_ref": "TEXT",
            },
        )
        self._ensure_columns(
            conn,
            "production_events",
            {
                "google_state": f"TEXT NOT NULL DEFAULT '{SYNC_STATE_PENDING}'",
                "google_last_attempted_at": "TEXT",
                "google_row_ref": "TEXT",
            },
        )
        self._ensure_columns(
            conn,
            "downtime_events",
            {
                "google_state": f"TEXT NOT NULL DEFAULT '{SYNC_STATE_PENDING}'",
                "google_last_attempted_at": "TEXT",
                "google_row_ref": "TEXT",
            },
        )

        conn.execute(
            """
            UPDATE scan_events
            SET google_scans_state = CASE
                    WHEN google_scans_synced = 1 THEN ?
                    WHEN google_scans_attempts > 0 AND COALESCE(google_scans_last_error, '') <> '' THEN ?
                    ELSE ?
                END,
                google_scans_last_attempted_at = COALESCE(google_scans_last_attempted_at, google_scans_synced_at)
            """,
            (SYNC_STATE_SYNCED, SYNC_STATE_FAILED, SYNC_STATE_PENDING),
        )
        conn.execute(
            """
            UPDATE scan_events
            SET google_sheet1_state = CASE
                    WHEN google_sheet1_synced = 1 THEN ?
                    WHEN google_sheet1_attempts > 0 AND COALESCE(google_sheet1_last_error, '') <> '' THEN ?
                    ELSE ?
                END,
                google_sheet1_last_attempted_at = COALESCE(google_sheet1_last_attempted_at, google_sheet1_synced_at)
            """,
            (SYNC_STATE_SYNCED, SYNC_STATE_FAILED, SYNC_STATE_PENDING),
        )
        conn.execute(
            """
            UPDATE production_events
            SET google_state = CASE
                    WHEN google_synced = 1 THEN ?
                    WHEN google_attempts > 0 AND COALESCE(google_last_error, '') <> '' THEN ?
                    ELSE ?
                END,
                google_last_attempted_at = COALESCE(google_last_attempted_at, google_synced_at)
            """,
            (SYNC_STATE_SYNCED, SYNC_STATE_FAILED, SYNC_STATE_PENDING),
        )
        conn.execute(
            """
            UPDATE downtime_events
            SET google_state = CASE
                    WHEN google_synced = 1 THEN ?
                    WHEN google_attempts > 0 AND COALESCE(google_last_error, '') <> '' THEN ?
                    ELSE ?
                END,
                google_last_attempted_at = COALESCE(google_last_attempted_at, google_synced_at)
            """,
            (SYNC_STATE_SYNCED, SYNC_STATE_FAILED, SYNC_STATE_PENDING),
        )

    def _initialize(self) -> None:
        with self._init_lock:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scan_events (
                        event_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        event_ts TEXT NOT NULL,
                        normalized_barcode TEXT NOT NULL,
                        status TEXT NOT NULL,
                        is_rework INTEGER NOT NULL DEFAULT 0,
                        product_code TEXT,
                        workcenter TEXT,
                        row_json TEXT NOT NULL,
                        local_committed_at TEXT NOT NULL,
                        excel_exported INTEGER NOT NULL DEFAULT 0,
                        excel_exported_at TEXT,
                        excel_export_attempts INTEGER NOT NULL DEFAULT 0,
                        excel_last_error TEXT,
                        google_scans_synced INTEGER NOT NULL DEFAULT 0,
                        google_scans_synced_at TEXT,
                        google_scans_attempts INTEGER NOT NULL DEFAULT 0,
                        google_scans_last_error TEXT,
                        google_sheet1_synced INTEGER NOT NULL DEFAULT 0,
                        google_sheet1_synced_at TEXT,
                        google_sheet1_attempts INTEGER NOT NULL DEFAULT 0,
                        google_sheet1_last_error TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS production_events (
                        event_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        event_ts TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        product_code TEXT,
                        workcenter TEXT,
                        row_json TEXT NOT NULL,
                        local_committed_at TEXT NOT NULL,
                        excel_exported INTEGER NOT NULL DEFAULT 0,
                        excel_exported_at TEXT,
                        excel_export_attempts INTEGER NOT NULL DEFAULT 0,
                        excel_last_error TEXT,
                        google_synced INTEGER NOT NULL DEFAULT 0,
                        google_synced_at TEXT,
                        google_attempts INTEGER NOT NULL DEFAULT 0,
                        google_last_error TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downtime_events (
                        event_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        event_ts TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        workcenter TEXT,
                        row_json TEXT NOT NULL,
                        local_committed_at TEXT NOT NULL,
                        excel_exported INTEGER NOT NULL DEFAULT 0,
                        excel_exported_at TEXT,
                        excel_export_attempts INTEGER NOT NULL DEFAULT 0,
                        excel_last_error TEXT,
                        google_synced INTEGER NOT NULL DEFAULT 0,
                        google_synced_at TEXT,
                        google_attempts INTEGER NOT NULL DEFAULT 0,
                        google_last_error TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scan_events_barcode ON scan_events(normalized_barcode)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scan_events_pending ON scan_events(google_scans_synced, google_sheet1_synced, excel_exported, event_ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_production_events_pending ON production_events(google_synced, excel_exported, event_ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_downtime_events_pending ON downtime_events(google_synced, excel_exported, event_ts)"
                )
                self._initialize_sync_state_columns(conn)

    def _fingerprint(self, prefix: str, row: dict[str, Any]) -> str:
        stable_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(f"{prefix}|{stable_json}".encode("utf-8")).hexdigest()

    def _insert_or_get_existing(self, conn: sqlite3.Connection, table: str, fingerprint: str, values: dict[str, Any]) -> tuple[str, bool]:
        existing = conn.execute(
            f"SELECT event_id FROM {table} WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing:
            return str(existing["event_id"]), False

        event_id = values.get("event_id") or uuid.uuid4().hex
        values = {**values, "event_id": event_id, "fingerprint": fingerprint}
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        return event_id, True

    def append_scan_event(
        self,
        row: dict[str, Any],
        *,
        normalized_barcode: str,
        bootstrap_synced: bool = False,
    ) -> tuple[str, bool]:
        scan_row = normalize_scan_row(dict(row))
        committed_at = _now_text()
        fingerprint = self._fingerprint("scan", scan_row)
        with closing(self._connect()) as conn, conn:
            return self._insert_or_get_existing(
                conn,
                "scan_events",
                fingerprint,
                {
                    "event_ts": str(scan_row.get("Timestamp", "")).strip(),
                    "normalized_barcode": str(normalized_barcode or "").strip().upper(),
                    "status": str(scan_row.get("Status", "")).strip(),
                    "is_rework": 1 if bool(scan_row.get("Is_Rework")) else 0,
                    "product_code": str(scan_row.get("Product Code", "")).strip(),
                    "workcenter": str(scan_row.get("Workcenter", "")).strip(),
                    "row_json": json.dumps(scan_row, ensure_ascii=False, sort_keys=True),
                    "local_committed_at": committed_at,
                    "excel_exported": 1 if bootstrap_synced else 0,
                    "excel_exported_at": committed_at if bootstrap_synced else None,
                    "google_scans_synced": 1 if bootstrap_synced else 0,
                    "google_scans_synced_at": committed_at if bootstrap_synced else None,
                    "google_scans_state": SYNC_STATE_SYNCED if bootstrap_synced else SYNC_STATE_PENDING,
                    "google_scans_last_attempted_at": committed_at if bootstrap_synced else None,
                    "google_sheet1_synced": 1 if bootstrap_synced else 0,
                    "google_sheet1_synced_at": committed_at if bootstrap_synced else None,
                    "google_sheet1_state": SYNC_STATE_SYNCED if bootstrap_synced else SYNC_STATE_PENDING,
                    "google_sheet1_last_attempted_at": committed_at if bootstrap_synced else None,
                },
            )

    def append_production_event(self, row: dict[str, Any]) -> tuple[str, bool]:
        production_row = {header: row.get(header, "") for header in PRODUCTION_HEADERS}
        fingerprint = self._fingerprint("production", production_row)
        with closing(self._connect()) as conn, conn:
            return self._insert_or_get_existing(
                conn,
                "production_events",
                fingerprint,
                {
                    "event_ts": str(production_row.get("Timestamp", "")).strip(),
                    "event_type": str(production_row.get("Event Type", "")).strip(),
                    "product_code": str(production_row.get("Product Code", "")).strip(),
                    "workcenter": str(production_row.get("Workcenter", "")).strip(),
                    "row_json": json.dumps(production_row, ensure_ascii=False, sort_keys=True),
                    "local_committed_at": _now_text(),
                },
            )

    def append_downtime_event(self, row: dict[str, Any]) -> tuple[str, bool]:
        downtime_row = {header: row.get(header, "") for header in DOWNTIME_HEADERS}
        fingerprint = self._fingerprint("downtime", downtime_row)
        with closing(self._connect()) as conn, conn:
            return self._insert_or_get_existing(
                conn,
                "downtime_events",
                fingerprint,
                {
                    "event_ts": str(downtime_row.get("Timestamp", "")).strip(),
                    "reason": str(downtime_row.get("Reason", "")).strip(),
                    "workcenter": str(downtime_row.get("Workcenter", "")).strip(),
                    "row_json": json.dumps(downtime_row, ensure_ascii=False, sort_keys=True),
                    "local_committed_at": _now_text(),
                },
            )

    def has_any_scan_events(self) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT 1 FROM scan_events LIMIT 1").fetchone()
        return row is not None

    def scan_exists(self, normalized_barcode: str) -> bool:
        barcode = str(normalized_barcode or "").strip().upper()
        if not barcode:
            return False
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM scan_events WHERE normalized_barcode = ? LIMIT 1",
                (barcode,),
            ).fetchone()
        return row is not None

    def load_known_barcodes(self) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT normalized_barcode FROM scan_events WHERE normalized_barcode <> ''"
            ).fetchall()
        return {str(row["normalized_barcode"]).strip().upper() for row in rows if row["normalized_barcode"]}

    def _rows_from_json(self, conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = conn.execute(query, params).fetchall()
        parsed: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["row_json"])
            for key in row.keys():
                if key in {"row_json"}:
                    continue
                payload[f"_{key}"] = row[key]
            parsed.append(payload)
        return parsed

    def fetch_scan_rows(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                "SELECT event_id, row_json FROM scan_events ORDER BY event_ts, local_committed_at, event_id",
            )

    def fetch_production_rows(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                "SELECT event_id, row_json FROM production_events ORDER BY event_ts, local_committed_at, event_id",
            )

    def fetch_downtime_rows(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                "SELECT event_id, row_json FROM downtime_events ORDER BY event_ts, local_committed_at, event_id",
            )

    def fetch_pending_scan_google_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                """
                SELECT event_id, row_json,
                       google_scans_synced, google_scans_state, google_scans_attempts,
                       google_scans_last_error, google_scans_last_attempted_at, google_scans_row_ref,
                       google_sheet1_synced, google_sheet1_state, google_sheet1_attempts,
                       google_sheet1_last_error, google_sheet1_last_attempted_at, google_sheet1_row_ref
                FROM scan_events
                WHERE google_scans_synced = 0 OR google_sheet1_synced = 0
                ORDER BY event_ts, local_committed_at, event_id
                """,
            )

    def fetch_pending_production_google_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                """
                SELECT event_id, row_json,
                       google_synced, google_state, google_attempts,
                       google_last_error, google_last_attempted_at, google_row_ref
                FROM production_events
                WHERE google_synced = 0
                ORDER BY event_ts, local_committed_at, event_id
                """,
            )

    def fetch_pending_downtime_google_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return self._rows_from_json(
                conn,
                """
                SELECT event_id, row_json,
                       google_synced, google_state, google_attempts,
                       google_last_error, google_last_attempted_at, google_row_ref
                FROM downtime_events
                WHERE google_synced = 0
                ORDER BY event_ts, local_committed_at, event_id
                """,
            )

    def mark_scan_google_synced(self, event_id: str, sink: str, row_ref: str | None = None) -> None:
        if sink not in {"scans", "sheet1"}:
            raise ValueError(f"Unsupported sink: {sink}")
        column_prefix = "google_scans" if sink == "scans" else "google_sheet1"
        synced_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"""
                UPDATE scan_events
                SET {column_prefix}_synced = 1,
                    {column_prefix}_synced_at = ?,
                    {column_prefix}_state = ?,
                    {column_prefix}_last_attempted_at = ?,
                    {column_prefix}_attempts = {column_prefix}_attempts + 1,
                    {column_prefix}_last_error = NULL,
                    {column_prefix}_row_ref = COALESCE(?, {column_prefix}_row_ref)
                WHERE event_id = ?
                """,
                (synced_at, SYNC_STATE_SYNCED, synced_at, row_ref, event_id),
            )

    def mark_scan_google_failed(self, event_id: str, sink: str, error: str) -> None:
        if sink not in {"scans", "sheet1"}:
            raise ValueError(f"Unsupported sink: {sink}")
        column_prefix = "google_scans" if sink == "scans" else "google_sheet1"
        attempted_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"""
                UPDATE scan_events
                SET {column_prefix}_state = ?,
                    {column_prefix}_last_attempted_at = ?,
                    {column_prefix}_attempts = {column_prefix}_attempts + 1,
                    {column_prefix}_last_error = ?
                WHERE event_id = ?
                """,
                (SYNC_STATE_FAILED, attempted_at, str(error or ""), event_id),
            )

    def mark_production_google_synced(self, event_id: str, row_ref: str | None = None) -> None:
        synced_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE production_events
                SET google_synced = 1,
                    google_synced_at = ?,
                    google_state = ?,
                    google_last_attempted_at = ?,
                    google_attempts = google_attempts + 1,
                    google_last_error = NULL,
                    google_row_ref = COALESCE(?, google_row_ref)
                WHERE event_id = ?
                """,
                (synced_at, SYNC_STATE_SYNCED, synced_at, row_ref, event_id),
            )

    def mark_production_google_failed(self, event_id: str, error: str) -> None:
        attempted_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE production_events
                SET google_state = ?,
                    google_last_attempted_at = ?,
                    google_attempts = google_attempts + 1,
                    google_last_error = ?
                WHERE event_id = ?
                """,
                (SYNC_STATE_FAILED, attempted_at, str(error or ""), event_id),
            )

    def mark_downtime_google_synced(self, event_id: str, row_ref: str | None = None) -> None:
        synced_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE downtime_events
                SET google_synced = 1,
                    google_synced_at = ?,
                    google_state = ?,
                    google_last_attempted_at = ?,
                    google_attempts = google_attempts + 1,
                    google_last_error = NULL,
                    google_row_ref = COALESCE(?, google_row_ref)
                WHERE event_id = ?
                """,
                (synced_at, SYNC_STATE_SYNCED, synced_at, row_ref, event_id),
            )

    def mark_downtime_google_failed(self, event_id: str, error: str) -> None:
        attempted_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE downtime_events
                SET google_state = ?,
                    google_last_attempted_at = ?,
                    google_attempts = google_attempts + 1,
                    google_last_error = ?
                WHERE event_id = ?
                """,
                (SYNC_STATE_FAILED, attempted_at, str(error or ""), event_id),
            )

    def get_google_sync_summary(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            scan_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN google_scans_synced = 0 THEN 1 ELSE 0 END) AS scans_pending,
                    SUM(CASE WHEN google_scans_state = ? AND google_scans_synced = 0 THEN 1 ELSE 0 END) AS scans_failed,
                    SUM(CASE WHEN google_sheet1_synced = 0 THEN 1 ELSE 0 END) AS sheet1_pending,
                    SUM(CASE WHEN google_sheet1_state = ? AND google_sheet1_synced = 0 THEN 1 ELSE 0 END) AS sheet1_failed
                FROM scan_events
                """,
                (SYNC_STATE_FAILED, SYNC_STATE_FAILED),
            ).fetchone()
            production_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN google_synced = 0 THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN google_state = ? AND google_synced = 0 THEN 1 ELSE 0 END) AS failed_count
                FROM production_events
                """,
                (SYNC_STATE_FAILED,),
            ).fetchone()
            downtime_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN google_synced = 0 THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN google_state = ? AND google_synced = 0 THEN 1 ELSE 0 END) AS failed_count
                FROM downtime_events
                """,
                (SYNC_STATE_FAILED,),
            ).fetchone()

        scans_pending = int((scan_row["scans_pending"] if scan_row else 0) or 0)
        sheet1_pending = int((scan_row["sheet1_pending"] if scan_row else 0) or 0)
        production_pending = int((production_row["pending_count"] if production_row else 0) or 0)
        downtime_pending = int((downtime_row["pending_count"] if downtime_row else 0) or 0)
        scans_failed = int((scan_row["scans_failed"] if scan_row else 0) or 0)
        sheet1_failed = int((scan_row["sheet1_failed"] if scan_row else 0) or 0)
        production_failed = int((production_row["failed_count"] if production_row else 0) or 0)
        downtime_failed = int((downtime_row["failed_count"] if downtime_row else 0) or 0)

        return {
            "pending_total": scans_pending + sheet1_pending + production_pending + downtime_pending,
            "failed_total": scans_failed + sheet1_failed + production_failed + downtime_failed,
            "scan_scans_pending": scans_pending,
            "scan_scans_failed": scans_failed,
            "scan_sheet1_pending": sheet1_pending,
            "scan_sheet1_failed": sheet1_failed,
            "production_pending": production_pending,
            "production_failed": production_failed,
            "downtime_pending": downtime_pending,
            "downtime_failed": downtime_failed,
        }

    def mark_all_excel_exported(self) -> None:
        exported_at = _now_text()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE scan_events
                SET excel_exported = 1,
                    excel_exported_at = ?,
                    excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = NULL
                WHERE excel_exported = 0
                """,
                (exported_at,),
            )
            conn.execute(
                """
                UPDATE production_events
                SET excel_exported = 1,
                    excel_exported_at = ?,
                    excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = NULL
                WHERE excel_exported = 0
                """,
                (exported_at,),
            )
            conn.execute(
                """
                UPDATE downtime_events
                SET excel_exported = 1,
                    excel_exported_at = ?,
                    excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = NULL
                WHERE excel_exported = 0
                """,
                (exported_at,),
            )

    def mark_excel_export_failed(self, error: str) -> None:
        message = str(error or "")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                UPDATE scan_events
                SET excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = ?
                WHERE excel_exported = 0
                """,
                (message,),
            )
            conn.execute(
                """
                UPDATE production_events
                SET excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = ?
                WHERE excel_exported = 0
                """,
                (message,),
            )
            conn.execute(
                """
                UPDATE downtime_events
                SET excel_export_attempts = excel_export_attempts + 1,
                    excel_last_error = ?
                WHERE excel_exported = 0
                """,
                (message,),
            )
