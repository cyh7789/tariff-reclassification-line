"""Resolve published duty rates from ordered HTS rows."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class DutyRate:
    hts8: str
    general: str
    special: str | None
    other: str | None
    resolved_from_row: int
    inherited: bool


def resolve(hts_code: str, hts_rows: Sequence[dict]) -> DutyRate | None:
    """Resolve the rate for an HTS code at its eight-digit level."""
    if len(hts_code) not in (8, 10) or not hts_code.isdigit():
        return None

    hts8 = hts_code[:8]
    matched_index = next(
        (
            index
            for index, row in enumerate(hts_rows)
            if row.get("htsno") == hts8
        ),
        None,
    )
    if matched_index is None:
        return None

    matched_indent = int(hts_rows[matched_index].get("indent") or 0)
    ceiling = matched_indent
    for index in range(matched_index, -1, -1):
        row = hts_rows[index]
        indent = int(row.get("indent") or 0)
        if index != matched_index and indent >= ceiling:
            continue
        ceiling = indent
        general = str(row.get("general") or "").strip()
        if general:
            return DutyRate(
                hts8=hts8,
                general=general,
                special=_optional_rate(row.get("special")),
                other=_optional_rate(row.get("other")),
                resolved_from_row=int(row["row_index"]),
                inherited=index != matched_index,
            )
        if indent == 0:
            break

    return None


def _optional_rate(value: object) -> str | None:
    rate = str(value or "").strip()
    return rate or None
