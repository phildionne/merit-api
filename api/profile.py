from __future__ import annotations

from typing import Sequence


def build_quality(statuses: Sequence[str]) -> dict[str, int | float]:
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
