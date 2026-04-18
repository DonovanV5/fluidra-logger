from __future__ import annotations

import os
import re
from typing import Any, Iterable


def resolve_zpl_file_path(filename: str, custom_dir: str | None, default_dir: str) -> str | None:
    if custom_dir:
        custom_path = os.path.join(custom_dir, filename)
        if os.path.exists(custom_path):
            return custom_path

    default_path = os.path.join(default_dir, filename)
    if os.path.exists(default_path):
        return default_path

    return None


def resolve_zpl_preset_path(preset_name: Any, custom_dir: str | None, default_dir: str) -> str:
    selected_preset = str(preset_name or "").strip()
    if not selected_preset:
        return ""

    search_dirs = []
    custom_dir = str(custom_dir or "").strip()
    if custom_dir:
        search_dirs.append(custom_dir)
    search_dirs.append(default_dir)

    for base_dir in search_dirs:
        preset_path = os.path.join(base_dir, selected_preset)
        if os.path.exists(preset_path):
            return preset_path
    return ""


def load_zpl_preset_names(custom_dir: str | None, default_dir: str) -> tuple[list[str], list[str]]:
    presets = []
    errors = []

    custom_dir = str(custom_dir or "").strip()
    if custom_dir:
        try:
            if os.path.exists(custom_dir):
                presets.extend([f for f in os.listdir(custom_dir) if f.lower().endswith('.zpl')])
        except Exception as e:
            errors.append(f"Error reading custom ZPL directory: {e}")

    try:
        if os.path.exists(default_dir):
            default_presets = [f for f in os.listdir(default_dir) if f.lower().endswith('.zpl') and f not in presets]
            presets.extend(default_presets)
    except Exception as e:
        errors.append(f"Error reading default ZPL directory: {e}")

    return presets, errors


def zpl_preset_paths(base_dir: str, preset_names: Iterable[str]) -> list[str]:
    return [os.path.join(base_dir, "zpl_presets", f) for f in preset_names]


def format_label_dimension(value: float) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def upsert_zpl_size_metadata(zpl_template: str, width_mm: float, height_mm: float) -> str:
    metadata_line = (
        f"^FX FMS_LABEL_SIZE_MM={format_label_dimension(width_mm)}x"
        f"{format_label_dimension(height_mm)}"
    )
    lines = str(zpl_template or "").splitlines()
    filtered_lines = [
        line for line in lines
        if not re.match(r'^\s*\^FX\s+FMS_LABEL_(SIZE_MM|WIDTH_MM|HEIGHT_MM)\s*[:=]', line, re.IGNORECASE)
    ]
    insert_index = 1 if filtered_lines and filtered_lines[0].strip().startswith("^XA") else 0
    filtered_lines.insert(insert_index, metadata_line)
    return "\n".join(filtered_lines)


def extract_zpl_dimensions_mm(preset_name: str = "", zpl_template: str = "") -> tuple[float, float] | None:
    template_text = str(zpl_template or "")

    size_match = re.search(
        r'FMS_LABEL_SIZE_MM\s*[:=]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)',
        template_text,
        re.IGNORECASE,
    )
    if size_match:
        return float(size_match.group(1)), float(size_match.group(2))

    width_match = re.search(r'FMS_LABEL_WIDTH_MM\s*[:=]\s*(\d+(?:\.\d+)?)', template_text, re.IGNORECASE)
    height_match = re.search(r'FMS_LABEL_HEIGHT_MM\s*[:=]\s*(\d+(?:\.\d+)?)', template_text, re.IGNORECASE)
    if width_match and height_match:
        return float(width_match.group(1)), float(height_match.group(1))

    pw_match = re.search(r'\^PW(\d+)\b', template_text)
    ll_match = re.search(r'\^LL(\d+)\b', template_text)
    if pw_match and ll_match:
        dpi = 203
        return (
            round(int(pw_match.group(1)) * 25.4 / dpi, 2),
            round(int(ll_match.group(1)) * 25.4 / dpi, 2),
        )

    name_match = re.search(r'(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)', str(preset_name or ""))
    if name_match:
        first = float(name_match.group(1))
        second = float(name_match.group(2))
        return min(first, second), max(first, second)

    return None


def coerce_print_quantity(raw_quantity: Any, fallback_quantity: Any = 2) -> int:
    if raw_quantity in (None, ""):
        raw_quantity = fallback_quantity

    try:
        quantity = int(str(raw_quantity).strip())
    except (TypeError, ValueError):
        quantity = 2

    return max(1, min(10, quantity))


def sanitize_zpl_payload(zpl_code: str) -> str:
    zpl = str(zpl_code or "").replace('\r\n', '\n').replace('\r', '\n').strip()
    zpl = re.sub(r'(\^XZ\s*)(?:"{3}|\'{3})\s*$', r'\1', zpl, flags=re.IGNORECASE).rstrip()

    if not re.search(r'\^XA', zpl, re.IGNORECASE) or not re.search(r'\^XZ', zpl, re.IGNORECASE):
        zpl = f"^XA\n{zpl}\n^XZ"

    return zpl


def validate_zpl_template(zpl_code: str, allowed_placeholders: set[str]) -> tuple[str, list[str], list[str]]:
    original = str(zpl_code or "")
    cleaned = sanitize_zpl_payload(original)
    errors = []
    warnings = []

    if not original.strip():
        errors.append("ZPL preset is empty.")

    start_match = re.search(r'\^XA', cleaned, re.IGNORECASE)
    end_matches = list(re.finditer(r'\^XZ', cleaned, re.IGNORECASE))
    if not start_match:
        errors.append("Missing ^XA start command.")
    if not end_matches:
        errors.append("Missing ^XZ end command.")
    if start_match and end_matches and start_match.start() > end_matches[-1].start():
        errors.append("^XA must appear before ^XZ.")

    trailing = cleaned[end_matches[-1].end():].strip() if end_matches else ""
    if trailing:
        errors.append("Unexpected text after final ^XZ.")

    placeholders = set(re.findall(r'\{([^{}]+)\}', cleaned))
    unknown_placeholders = sorted(placeholders - allowed_placeholders)
    if unknown_placeholders:
        errors.append(f"Unknown placeholder(s): {', '.join(unknown_placeholders)}.")

    if not ({"barcode_text", "Barc"} & placeholders) and "^BC" not in cleaned.upper():
        warnings.append("No barcode placeholder or ^BC barcode command was found.")

    if original.strip() != cleaned.strip():
        warnings.append("Trailing or malformed ZPL wrapper text will be cleaned on save.")

    return cleaned, errors, warnings


def prepare_zpl_print_job(zpl_code: str, quantity: int) -> str:
    quantity = max(1, min(10, int(quantity)))
    zpl = sanitize_zpl_payload(zpl_code)
    quantity_command = f"^PQ{quantity}"

    if re.search(r'\^PQ', zpl, re.IGNORECASE):
        zpl = re.sub(r'\^PQ[^^\r\n]*', quantity_command, zpl, count=1, flags=re.IGNORECASE)
    else:
        zpl = re.sub(r'\^XZ\s*$', f"{quantity_command}\n^XZ", zpl, count=1, flags=re.IGNORECASE)

    return zpl + "\n"


def zpl_command_tokens(zpl_code: str):
    for match in re.finditer(r'([\^~])([A-Za-z0-9@]{1,2})([^\^~]*)', str(zpl_code or ""), re.DOTALL):
        yield match.group(1), match.group(2).upper(), match.group(3).strip("\r\n")


def code128_patterns() -> list[str]:
    return [
        "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
        "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
        "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
        "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
        "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
        "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
        "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
        "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
        "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
        "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
        "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
        "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
        "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
        "211214", "211232", "2331112",
    ]


def fit_preview_image(image: Any, max_width: int = 680, max_height: int = 620) -> Any:
    display_image = image.copy()
    display_image.thumbnail((max_width, max_height))
    return display_image


def printer_is_available(win32print_module: Any, printer_name: str | None = None) -> bool:
    if not printer_name:
        printer_name = win32print_module.GetDefaultPrinter()
    handle = win32print_module.OpenPrinter(printer_name)
    try:
        info = win32print_module.GetPrinter(handle, 2)
        status = info.get('Status', 0)
        attributes = info.get('Attributes', 0)
        printer_status_error = 0x00000002
        printer_status_offline = 0x00000080
        printer_attribute_work_offline = 0x00040000
        if status & (printer_status_error | printer_status_offline):
            return False
        if attributes & printer_attribute_work_offline:
            return False
        return True
    finally:
        win32print_module.ClosePrinter(handle)


def send_raw_printer_job(win32print_module: Any, raw_data: str | bytes, printer_name: str, job_name: str) -> bytes:
    payload = raw_data.encode('utf-8') if isinstance(raw_data, str) else raw_data
    handle = win32print_module.OpenPrinter(printer_name)
    try:
        doc_info = (job_name, None, "RAW")
        win32print_module.StartDocPrinter(handle, 1, doc_info)
        try:
            win32print_module.StartPagePrinter(handle)
            win32print_module.WritePrinter(handle, payload)
            win32print_module.EndPagePrinter(handle)
        finally:
            win32print_module.EndDocPrinter(handle)
    finally:
        win32print_module.ClosePrinter(handle)
    return payload
