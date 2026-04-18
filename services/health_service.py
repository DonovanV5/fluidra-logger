from __future__ import annotations

from typing import Any

from fms_logging import (
    HEALTH_ERROR,
    HEALTH_OK,
    HEALTH_UNKNOWN,
    HEALTH_WARNING,
    format_health_timestamp,
    worst_health_state,
)


def health_abbreviation(state: str) -> str:
    mapping = {
        HEALTH_OK: "OK",
        HEALTH_WARNING: "WARN",
        HEALTH_ERROR: "ERR",
        HEALTH_UNKNOWN: "UNK",
    }
    return mapping.get(state, "UNK")


def format_health_display_texts(
    health_signals: dict[str, dict[str, Any]],
    last_successful_scan_write_at: Any,
    last_successful_google_write_at: Any,
    last_successful_server_csv_write_at: Any,
    last_duplicate_check_failure_at: Any,
) -> tuple[str, str, str, str]:
    integrations = [
        f"L:{health_abbreviation(health_signals.get('local_store', {}).get('state', HEALTH_UNKNOWN))}",
        f"S:{health_abbreviation(health_signals.get('google_sheets', {}).get('state', HEALTH_UNKNOWN))}",
        f"CSV:{health_abbreviation(health_signals.get('server_csv', {}).get('state', HEALTH_UNKNOWN))}",
        f"E:{health_abbreviation(health_signals.get('excel', {}).get('state', HEALTH_UNKNOWN))}",
        f"P:{health_abbreviation(health_signals.get('printer', {}).get('state', HEALTH_UNKNOWN))}",
        f"T:{health_abbreviation(health_signals.get('teraoka', {}).get('state', HEALTH_UNKNOWN))}",
    ]
    integration_text = "Health " + " ".join(integrations)

    scan_state = health_signals.get("scan_write", {}).get("state", HEALTH_UNKNOWN)
    google_state = health_signals.get("google_write", {}).get("state", HEALTH_UNKNOWN)
    server_csv_state = health_signals.get("server_csv", {}).get("state", HEALTH_UNKNOWN)
    dup_state = health_signals.get("duplicate_check", {}).get("state", HEALTH_UNKNOWN)
    writes_text = (
        "Writes "
        f"Sc:{health_abbreviation(scan_state)} {format_health_timestamp(last_successful_scan_write_at)} "
        f"G:{health_abbreviation(google_state)} {format_health_timestamp(last_successful_google_write_at)} "
        f"CSV:{health_abbreviation(server_csv_state)} "
        f"{format_health_timestamp(last_successful_server_csv_write_at)} "
        f"D:{health_abbreviation(dup_state)} {format_health_timestamp(last_duplicate_check_failure_at)}"
    )

    integration_state = worst_health_state(
        health_signals.get("local_store", {}).get("state", HEALTH_UNKNOWN),
        health_signals.get("google_sheets", {}).get("state", HEALTH_UNKNOWN),
        server_csv_state,
        health_signals.get("excel", {}).get("state", HEALTH_UNKNOWN),
        health_signals.get("printer", {}).get("state", HEALTH_UNKNOWN),
        health_signals.get("teraoka", {}).get("state", HEALTH_UNKNOWN),
    )
    write_state = worst_health_state(scan_state, google_state, server_csv_state, dup_state)
    return integration_text, writes_text, integration_state, write_state
