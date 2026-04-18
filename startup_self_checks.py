from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
import os
import sqlite3
from typing import Iterable

from fms_logging import HEALTH_ERROR, HEALTH_OK, HEALTH_UNKNOWN, HEALTH_WARNING, normalize_health_state


@dataclass(frozen=True)
class StartupCheckResult:
    name: str
    state: str
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", normalize_health_state(self.state))
        object.__setattr__(self, "detail", str(self.detail or "").strip())


def check_directory(path: str, label: str, *, create_if_missing: bool = False) -> StartupCheckResult:
    target = os.path.abspath(path)
    if os.path.isdir(target):
        return StartupCheckResult(label, HEALTH_OK, f"{label} ready at {target}.")
    if os.path.exists(target) and not os.path.isdir(target):
        return StartupCheckResult(label, HEALTH_ERROR, f"{label} path is not a directory: {target}.")
    if not create_if_missing:
        return StartupCheckResult(label, HEALTH_ERROR, f"{label} directory is missing: {target}. Create it before startup.")
    try:
        os.makedirs(target, exist_ok=True)
        return StartupCheckResult(label, HEALTH_OK, f"{label} created at {target}.")
    except Exception as exc:
        return StartupCheckResult(
            label,
            HEALTH_ERROR,
            f"{label} could not be created at {target}: {exc}. Check permissions and free disk space.",
        )


def check_required_file(path: str, label: str, *, guidance: str) -> StartupCheckResult:
    target = os.path.abspath(path)
    if os.path.isfile(target):
        return StartupCheckResult(label, HEALTH_OK, f"{label} found at {target}.")
    return StartupCheckResult(label, HEALTH_ERROR, f"{label} missing at {target}. {guidance}")


def check_optional_json_file(
    path: str,
    label: str,
    *,
    missing_detail: str,
) -> StartupCheckResult:
    target = os.path.abspath(path)
    if not os.path.exists(target):
        return StartupCheckResult(label, HEALTH_OK, missing_detail)
    if not os.path.isfile(target):
        return StartupCheckResult(label, HEALTH_ERROR, f"{label} path is not a file: {target}.")
    try:
        with open(target, "r", encoding="utf-8") as handle:
            json.load(handle)
        return StartupCheckResult(label, HEALTH_OK, f"{label} loaded from {target}.")
    except Exception as exc:
        return StartupCheckResult(
            label,
            HEALTH_ERROR,
            f"{label} is not readable JSON at {target}: {exc}. Restore a valid JSON file or remove it so defaults can be recreated.",
        )


def check_sqlite_target(db_path: str) -> StartupCheckResult:
    target = os.path.abspath(db_path)
    parent = os.path.dirname(target)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with closing(sqlite3.connect(target, timeout=5)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("SELECT 1")
        return StartupCheckResult("SQLite local store", HEALTH_OK, f"SQLite is writable at {target}.")
    except Exception as exc:
        return StartupCheckResult(
            "SQLite local store",
            HEALTH_ERROR,
            f"SQLite is not writable at {target}: {exc}. Check permissions, file locks, and disk space.",
        )


def check_google_workbook_access(
    workbook: object,
    *,
    workbook_name: str,
    required_sheets: Iterable[str],
    on_demand_sheets: Iterable[str] = (),
) -> StartupCheckResult:
    try:
        worksheets = list(workbook.worksheets())  # type: ignore[call-arg]
        titles = sorted(str(getattr(ws, "title", "") or "").strip() for ws in worksheets)
    except Exception as exc:
        return StartupCheckResult(
            "Google workbook",
            HEALTH_ERROR,
            f"Could not read workbook '{workbook_name}': {exc}. Check Google connectivity, sharing, and service-account access.",
        )

    missing_required = [name for name in required_sheets if name not in titles]
    if missing_required:
        return StartupCheckResult(
            "Google workbook",
            HEALTH_ERROR,
            f"Workbook '{workbook_name}' is reachable but missing required sheets: {', '.join(missing_required)}.",
        )

    missing_on_demand = [name for name in on_demand_sheets if name not in titles]
    detail = f"Workbook '{workbook_name}' reachable with required sheets ready."
    if missing_on_demand:
        detail = (
            f"{detail} Missing on-demand sheets: {', '.join(missing_on_demand)}; "
            "they will be created when the logger next syncs."
        )
    return StartupCheckResult("Google workbook", HEALTH_OK, detail)


def check_printer_target(configured_printer: str, available_printers: Iterable[str]) -> StartupCheckResult:
    configured = str(configured_printer or "").strip()
    names = [str(item or "").strip() for item in available_printers if str(item or "").strip()]
    lowered = {name.lower(): name for name in names}

    if not configured:
        return StartupCheckResult("Printer target", HEALTH_WARNING, "No configured printer name was provided.")
    if configured.lower() in lowered:
        return StartupCheckResult("Printer target", HEALTH_OK, f"Configured printer ready: {lowered[configured.lower()]}.")

    zebra_like = [name for name in names if "zebra" in name.lower() or "zdesigner" in name.lower()]
    if zebra_like:
        return StartupCheckResult(
            "Printer target",
            HEALTH_WARNING,
            f"Configured printer '{configured}' was not found. Zebra-like printers available: {', '.join(zebra_like)}. Verify the configured printer name.",
        )
    return StartupCheckResult(
        "Printer target",
        HEALTH_WARNING,
        f"Configured printer '{configured}' was not found. Verify the Windows printer mapping and cable/network connection.",
    )


def check_teraoka_readiness(
    *,
    enabled: bool,
    config_path: str,
    wsdl_url: str,
    supervisor: str,
    workcenter: str,
) -> StartupCheckResult:
    target = os.path.abspath(config_path)
    if not enabled:
        if os.path.isfile(target):
            return StartupCheckResult("Teraoka config", HEALTH_UNKNOWN, f"Teraoka is disabled. Config is present at {target}.")
        return StartupCheckResult("Teraoka config", HEALTH_UNKNOWN, "Teraoka is disabled. Config file is not required for startup.")

    missing_fields = []
    if not str(wsdl_url or "").strip():
        missing_fields.append("WSDL URL")
    if not str(supervisor or "").strip():
        missing_fields.append("supervisor")
    if not str(workcenter or "").strip():
        missing_fields.append("workcenter")
    if missing_fields:
        return StartupCheckResult(
            "Teraoka config",
            HEALTH_ERROR,
            f"Teraoka is enabled but missing required settings: {', '.join(missing_fields)}.",
        )

    if not os.path.exists(target):
        return StartupCheckResult(
            "Teraoka config",
            HEALTH_WARNING,
            f"Teraoka is enabled but config file is missing at {target}. Built-in defaults are active; verify workcenter and service settings.",
        )

    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return StartupCheckResult(
            "Teraoka config",
            HEALTH_ERROR,
            f"Teraoka config is unreadable at {target}: {exc}. Restore a valid JSON config before relying on Teraoka.",
        )

    configured_workcenters = payload.get("workcenters", [])
    workcenter_ids = {
        str(item.get("id", "")).strip()
        for item in configured_workcenters
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    if workcenter_ids and str(workcenter or "").strip() not in workcenter_ids:
        return StartupCheckResult(
            "Teraoka config",
            HEALTH_WARNING,
            f"Teraoka config loaded from {target}, but workcenter '{workcenter}' is not listed there. Verify the selected workcenter before production.",
        )

    return StartupCheckResult("Teraoka config", HEALTH_OK, f"Teraoka config ready at {target}.")


def summarize_startup_checks(results: Iterable[StartupCheckResult]) -> dict[str, int]:
    summary = {
        HEALTH_OK: 0,
        HEALTH_WARNING: 0,
        HEALTH_ERROR: 0,
        HEALTH_UNKNOWN: 0,
    }
    for result in results:
        summary[normalize_health_state(result.state)] += 1
    return summary
