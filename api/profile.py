from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict


class QualitySummary(TypedDict):
    total: int
    ok: int
    nodata: int
    out_of_coverage: int
    coverage_ratio: float


def build_quality(statuses: Sequence[str]) -> QualitySummary:
    total = len(statuses)
    ok = statuses.count("ok")
    nodata = statuses.count("nodata")
    out_of_coverage = statuses.count("out_of_coverage")
    coverage_ratio = round(ok / total, 10) if total > 0 else 0.0
    return {
        "total": total,
        "ok": ok,
        "nodata": nodata,
        "out_of_coverage": out_of_coverage,
        "coverage_ratio": coverage_ratio,
    }
