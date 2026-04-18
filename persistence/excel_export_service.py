from __future__ import annotations

from typing import Any, Callable


def build_export_dataframe(pd_module: Any, rows: list[dict[str, Any]], headers: list[str], normalize_scans: bool = False, scan_normalizer: Callable[[Any], Any] | None = None):
    if normalize_scans:
        if scan_normalizer is None:
            raise ValueError("scan_normalizer is required when normalize_scans is True")
        return scan_normalizer(pd_module.DataFrame(rows))

    df = pd_module.DataFrame(rows)
    for header in headers:
        if header not in df.columns:
            df[header] = ""
    if df.empty:
        return pd_module.DataFrame(columns=headers)
    return df[headers].fillna("")


def style_excel_export_sheet(worksheet: Any, pattern_fill_cls: type[Any]) -> None:
    header_fill = pattern_fill_cls(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    for cell in worksheet[1]:
        cell.fill = header_fill
    for col in worksheet.columns:
        try:
            column_letter = col[0].column_letter
            worksheet.column_dimensions[column_letter].width = 20
        except Exception:
            continue
