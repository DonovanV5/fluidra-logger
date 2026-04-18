from __future__ import annotations


def parse_expected_cycle(raw):
    try:
        val = str(raw).replace(",", ".").split()[0]
        return float(val)
    except Exception:
        return None
