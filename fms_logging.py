import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any


HEALTH_OK = "OK"
HEALTH_WARNING = "WARNING"
HEALTH_ERROR = "ERROR"
HEALTH_UNKNOWN = "UNKNOWN"

HEALTH_STATES = {HEALTH_OK, HEALTH_WARNING, HEALTH_ERROR, HEALTH_UNKNOWN}
HEALTH_STATE_ORDER = {
    HEALTH_OK: 0,
    HEALTH_UNKNOWN: 1,
    HEALTH_WARNING: 2,
    HEALTH_ERROR: 3,
}
HEALTH_STATE_COLORS = {
    HEALTH_OK: "green",
    HEALTH_WARNING: "orange",
    HEALTH_ERROR: "red",
    HEALTH_UNKNOWN: "gray",
}

_LOG_CONTEXT: dict[str, Any] = {}
_LOG_CONTEXT_LOCK = threading.Lock()


def configure_app_logger(app_name: str, log_filename: str, base_path: str, level: int = logging.INFO) -> logging.Logger:
    """Configure a rotating file logger once per application."""
    logger = logging.getLogger(app_name)
    if getattr(logger, "_fms_logger_configured", False):
        return logger

    log_dir = os.path.join(base_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_filename),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        os.path.join(log_dir, f"{os.path.splitext(log_filename)[0]}_errors.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger._fms_logger_configured = True  # type: ignore[attr-defined]
    return logger


def set_log_context(**fields: Any) -> dict[str, Any]:
    """Set fields that should be added to every structured log event."""
    clean_fields = {key: value for key, value in fields.items() if value is not None}
    with _LOG_CONTEXT_LOCK:
        _LOG_CONTEXT.update(clean_fields)
        return dict(_LOG_CONTEXT)


def clear_log_context(*field_names: str) -> dict[str, Any]:
    with _LOG_CONTEXT_LOCK:
        if field_names:
            for field_name in field_names:
                _LOG_CONTEXT.pop(field_name, None)
        else:
            _LOG_CONTEXT.clear()
        return dict(_LOG_CONTEXT)


def get_log_context() -> dict[str, Any]:
    with _LOG_CONTEXT_LOCK:
        return dict(_LOG_CONTEXT)


def make_correlation_id(prefix: str) -> str:
    safe_prefix = "".join(ch for ch in str(prefix or "id").lower() if ch.isalnum() or ch in {"_", "-"}).strip("-_")
    safe_prefix = safe_prefix or "id"
    return f"{safe_prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def elapsed_ms(start_perf: float) -> float:
    return round((time.perf_counter() - float(start_perf)) * 1000.0, 2)


def structured_message(event: str, **fields: Any) -> str:
    with _LOG_CONTEXT_LOCK:
        context = dict(_LOG_CONTEXT)
    payload = {"event": event, **context, **fields}
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, structured_message(event, **fields))


def log_timing(
    logger: logging.Logger,
    level: int,
    event: str,
    start_perf: float,
    *,
    min_duration_ms: float = 0.0,
    **fields: Any,
) -> float:
    duration = elapsed_ms(start_perf)
    if duration >= float(min_duration_ms or 0.0):
        log_event(logger, level, event, duration_ms=duration, **fields)
    return duration


def normalize_health_state(state: str | None) -> str:
    value = str(state or HEALTH_UNKNOWN).strip().upper()
    return value if value in HEALTH_STATES else HEALTH_UNKNOWN


def make_health_signal(
    state: str = HEALTH_UNKNOWN,
    detail: str = "",
    updated_at: datetime | None = None,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "state": normalize_health_state(state),
        "detail": str(detail or "").strip(),
        "updated_at": updated_at if updated_at is not None else datetime.now(),
        **fields,
    }


def set_health_signal(
    signals: dict[str, dict[str, Any]],
    name: str,
    state: str,
    detail: str = "",
    updated_at: datetime | None = None,
    **fields: Any,
) -> dict[str, Any]:
    signal = make_health_signal(state=state, detail=detail, updated_at=updated_at, **fields)
    signals[name] = signal
    return signal


def format_health_timestamp(value: datetime | None) -> str:
    if value is None:
        return "--"
    return value.strftime("%H:%M:%S")


def health_state_color(state: str) -> str:
    return HEALTH_STATE_COLORS.get(normalize_health_state(state), HEALTH_STATE_COLORS[HEALTH_UNKNOWN])


def worst_health_state(*states: str) -> str:
    valid_states = [normalize_health_state(state) for state in states if state]
    if not valid_states:
        return HEALTH_UNKNOWN
    return max(valid_states, key=lambda item: HEALTH_STATE_ORDER[item])


def format_health_signal(name: str, signal: dict[str, Any] | None, include_time: bool = False) -> str:
    if not signal:
        return f"{name}: {HEALTH_UNKNOWN}"

    state = normalize_health_state(signal.get("state"))
    text = f"{name}: {state}"
    detail = str(signal.get("detail", "") or "").strip()
    if detail:
        text = f"{text} ({detail})"
    if include_time:
        text = f"{text} @ {format_health_timestamp(signal.get('updated_at'))}"
    return text
