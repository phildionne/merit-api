from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict


class QualitySummary(TypedDict):
    total: int
    ok: int
    nodata: int
    out_of_coverage: int
    coverage_ratio: float


def build_quality(statuses: Iterable[str]) -> QualitySummary:
    total = 0
    ok = 0
    nodata = 0
    out_of_coverage = 0
    for status in statuses:
        total += 1
        if status == "ok":
            ok += 1
        elif status == "nodata":
            nodata += 1
        elif status == "out_of_coverage":
            out_of_coverage += 1
    coverage_ratio = round(ok / total, 10) if total > 0 else 0.0
    return {
        "total": total,
        "ok": ok,
        "nodata": nodata,
        "out_of_coverage": out_of_coverage,
        "coverage_ratio": coverage_ratio,
    }
