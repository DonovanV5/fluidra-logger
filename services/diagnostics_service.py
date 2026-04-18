from __future__ import annotations

import json
import os
import platform
import re
import sys
from datetime import datetime
from typing import Any

from fms_logging import HEALTH_UNKNOWN, format_health_timestamp
from schema_contract import format_contract_timestamp


SENSITIVE_DIAGNOSTIC_KEY_RE = re.compile(
    r"(password|secret|token|private|credential|api[_-]?key)",
    re.IGNORECASE,
)


def redact_diagnostics_data(value: Any, key_name: str = "") -> Any:
    sensitive = SENSITIVE_DIAGNOSTIC_KEY_RE.search(str(key_name or ""))
    if sensitive:
        return "***REDACTED***"
    if isinstance(value, dict):
        return {key: redact_diagnostics_data(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_diagnostics_data(item, key_name) for item in value]
    return value


def read_redacted_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return redact_diagnostics_data(json.load(f))
    except Exception as e:
        return {"error": str(e), "path": path}


def format_health_details(
    app_version: str,
    workcenter: Any,
    include_workcenter: bool,
    health_signals: dict[str, dict[str, Any]],
    local_store: Any,
    last_print_record: dict[str, Any] | None,
    print_audit_headers: list[str],
) -> str:
    lines = [f"Application: {app_version}"]
    if include_workcenter:
        lines.append(f"Workcenter: {workcenter}")
    lines.append("")
    lines.append("Health")
    for name in sorted(health_signals.keys()):
        signal = health_signals.get(name, {})
        state = signal.get("state", HEALTH_UNKNOWN)
        detail = signal.get("detail", "")
        updated = format_health_timestamp(signal.get("updated_at"))
        lines.append(f"{name}: {state} | {updated} | {detail}")

    lines.append("")
    lines.append("Google Sync Backlog")
    try:
        summary = local_store.get_google_sync_summary() if local_store else {}
    except Exception as e:
        summary = {"error": str(e)}
    if summary:
        for key in sorted(summary.keys()):
            lines.append(f"{key}: {summary.get(key)}")
    else:
        lines.append("No local sync summary available.")

    lines.append("")
    lines.append("Last Print")
    if last_print_record:
        for key in print_audit_headers:
            lines.append(f"{key}: {last_print_record.get(key, '')}")
    else:
        lines.append("No print attempted in this session.")
    return "\n".join(lines)


def diagnostics_metadata(
    *,
    app_version: str,
    app_run_id: str,
    log_context: dict[str, Any],
    host: str,
    base_path: str,
    workcenter: str,
    logging_backend: str,
    server_csv_dir: str,
    server_csv_station_dir: str,
    selected_zpl_preset: str,
    label_width_mm: float,
    label_height_mm: float,
    print_quantity: Any,
    auto_downtime_multiplier: Any,
    health_signals: dict[str, dict[str, Any]],
    google_credentials_file: str,
    excel_file: str,
    local_db_file: str,
    print_audit_file: str,
) -> dict[str, Any]:
    return {
        "created_at": format_contract_timestamp(datetime.now()),
        "app": app_version,
        "app_run_id": app_run_id,
        "log_context": log_context,
        "host": host,
        "windows_user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "python_version": sys.version,
        "platform": platform.platform(),
        "base_path": base_path,
        "workcenter": workcenter,
        "logging_backend": logging_backend,
        "server_csv_dir": server_csv_dir,
        "server_csv_station_dir": server_csv_station_dir,
        "selected_zpl_preset": selected_zpl_preset,
        "label_width_mm": label_width_mm,
        "label_height_mm": label_height_mm,
        "print_quantity": print_quantity,
        "auto_downtime_multiplier": auto_downtime_multiplier,
        "health_signals": redact_diagnostics_data(health_signals),
        "google_credentials_present": os.path.exists(google_credentials_file),
        "excel_file": excel_file,
        "local_db_file": local_db_file,
        "print_audit_file": print_audit_file,
    }
