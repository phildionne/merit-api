from __future__ import annotations

import math
from typing import Sequence


EARTH_RADIUS_M = 6371008.8
CHAINAGE_EPSILON_M = 1e-6
MAX_LINE_LENGTH_M = 50_000.0


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def build_chainage_m(points: Sequence[tuple[float, float]]) -> list[float]:
    if not points:
        return []

    chainage = [0.0]
    total = 0.0
    for idx in range(1, len(points)):
        prev_lat, prev_lng = points[idx - 1]
        lat, lng = points[idx]
        total += haversine_distance_m(prev_lat, prev_lng, lat, lng)
        chainage.append(total)
    return chainage


def lat_lng_to_unit_vector(lat: float, lng: float) -> tuple[float, float, float]:
    lat_r = math.radians(lat)
    lng_r = math.radians(lng)
    cos_lat = math.cos(lat_r)
    return (
        cos_lat * math.cos(lng_r),
        cos_lat * math.sin(lng_r),
        math.sin(lat_r),
    )


def unit_vector_to_lat_lng(x: float, y: float, z: float) -> tuple[float, float]:
    hyp = math.hypot(x, y)
    return (math.degrees(math.atan2(z, hyp)), math.degrees(math.atan2(y, x)))


def interpolate_geodesic_point(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    fraction: float,
) -> tuple[float, float]:
    if fraction <= 0.0:
        return (start_lat, start_lng)
    if fraction >= 1.0:
        return (end_lat, end_lng)

    start_vec = lat_lng_to_unit_vector(start_lat, start_lng)
    end_vec = lat_lng_to_unit_vector(end_lat, end_lng)
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(start_vec, end_vec))))
    angle = math.acos(dot)

    if angle <= 1e-12:
        return (start_lat, start_lng)

    sin_angle = math.sin(angle)
    if abs(sin_angle) <= 1e-12:
        x = start_vec[0] * (1.0 - fraction) + end_vec[0] * fraction
        y = start_vec[1] * (1.0 - fraction) + end_vec[1] * fraction
        z = start_vec[2] * (1.0 - fraction) + end_vec[2] * fraction
        norm = math.sqrt(x * x + y * y + z * z)
        if norm <= 1e-12:
            return (
                start_lat + (end_lat - start_lat) * fraction,
                start_lng + (end_lng - start_lng) * fraction,
            )
        return unit_vector_to_lat_lng(x / norm, y / norm, z / norm)

    start_scale = math.sin((1.0 - fraction) * angle) / sin_angle
    end_scale = math.sin(fraction * angle) / sin_angle
    x = start_vec[0] * start_scale + end_vec[0] * end_scale
    y = start_vec[1] * start_scale + end_vec[1] * end_scale
    z = start_vec[2] * start_scale + end_vec[2] * end_scale
    norm = math.sqrt(x * x + y * y + z * z)
    return unit_vector_to_lat_lng(x / norm, y / norm, z / norm)


def build_sample_chainages_m(line_length_m: float, density_m: float) -> list[float]:
    if line_length_m <= 0.0:
        return []

    sample_count = int(math.floor((line_length_m + CHAINAGE_EPSILON_M) / density_m))
    chainages = [density_m * idx for idx in range(1, sample_count + 1)]
    if chainages and math.isclose(chainages[-1], line_length_m, abs_tol=CHAINAGE_EPSILON_M):
        chainages[-1] = line_length_m
    return chainages


def interpolate_samples_along_line(
    line_coords: Sequence[tuple[float, float]],
    vertex_chainages: Sequence[float],
    sample_chainages: Sequence[float],
) -> list[tuple[float, float]]:
    if not sample_chainages:
        return []

    sampled_coords: list[tuple[float, float]] = []
    segment_idx = 1

    for chainage in sample_chainages:
        while segment_idx < len(vertex_chainages) - 1 and vertex_chainages[segment_idx] + CHAINAGE_EPSILON_M < chainage:
            segment_idx += 1

        start_chainage = vertex_chainages[segment_idx - 1]
        end_chainage = vertex_chainages[segment_idx]
        start_lat, start_lng = line_coords[segment_idx - 1]
        end_lat, end_lng = line_coords[segment_idx]

        if end_chainage <= start_chainage + CHAINAGE_EPSILON_M:
            sampled_coords.append((end_lat, end_lng))
            continue

        fraction = min(1.0, max(0.0, (chainage - start_chainage) / (end_chainage - start_chainage)))
        sampled_coords.append(
            interpolate_geodesic_point(
                start_lat,
                start_lng,
                end_lat,
                end_lng,
                fraction,
            )
        )

    return sampled_coords


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
