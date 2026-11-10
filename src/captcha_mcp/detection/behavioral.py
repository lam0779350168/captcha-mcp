"""Phân tích hành vi để phát hiện pattern robotic.

Input: chuỗi event đã ghi lại, ví dụ
  [{"type": "mouse_move", "t": 0.0, "x": 10, "y": 10}, {"type": "click", "t": 0.42, ...}, ...]

Output: metrics + robot_probability + findings (không phải verdict tuyệt đối).
"""

from __future__ import annotations

import itertools
import math


def _intervals(events: list[dict]) -> list[float]:
    times = sorted(float(e["t"]) for e in events if "t" in e)
    return [b - a for a, b in itertools.pairwise(times)]


def _cv(values: list[float]) -> float:
    """Hệ số biến thiên; 0 = hoàn toàn đều (robotic)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var) / mean


def _straightness(points: list[tuple[float, float]]) -> float:
    """1.0 = đường thẳng (robotic), ~0 = đường cong tự nhiên."""
    if len(points) < 3:
        return 1.0
    (x0, y0), (x1, y1) = points[0], points[-1]
    direct = math.hypot(x1 - x0, y1 - y0)
    path = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(points))
    if path == 0:
        return 1.0
    return round(direct / path, 3)


def analyze_behavior(events: list[dict]) -> dict:
    """Chấm điểm 'giống robot' cho một chuỗi event."""
    findings: list[dict] = []
    if not events:
        return {
            "events": 0,
            "robot_probability": 0.0,
            "verdict": "no-data",
            "metrics": {},
            "findings": [{"severity": "low", "signal": "events", "detail": "không có event nào"}],
        }

    intervals = _intervals(events)
    cv = _cv(intervals)
    moves = [
        (float(e["x"]), float(e["y"]))
        for e in events
        if e.get("type") in ("mouse_move", "mousemove") and "x" in e and "y" in e
    ]
    straight = _straightness(moves) if len(moves) >= 3 else None
    duration = float(events[-1]["t"]) - float(events[0]["t"]) if "t" in events[0] else 0.0
    rate = len(events) / duration if duration > 0 else 0.0

    if intervals and cv < 0.12:
        findings.append(
            {
                "severity": "high",
                "signal": "timing",
                "detail": f"khoảng lặp gần như đều (CV={cv:.3f}) — dấu hiệu máy",
            }
        )
    if straight is not None and straight > 0.95:
        findings.append(
            {
                "severity": "high",
                "signal": "mouse_path",
                "detail": f"đường chuột thẳng tuyến tính (straightness={straight})",
            }
        )
    if straight is not None and straight < 0.6:
        findings.append(
            {
                "severity": "info",
                "signal": "mouse_path",
                "detail": f"đường chuột cong tự nhiên (straightness={straight})",
            }
        )
    if rate > 12:
        findings.append(
            {
                "severity": "medium",
                "signal": "event_rate",
                "detail": f"{rate:.1f} event/giây — nhanh bất thường",
            }
        )
    if duration and duration < 1.0 and len(events) > 5:
        findings.append(
            {
                "severity": "medium",
                "signal": "duration",
                "detail": f"{len(events)} event trong {duration:.2f}s",
            }
        )

    penalty = sum(
        {"high": 0.4, "medium": 0.2, "low": 0.1, "info": 0.0}.get(f["severity"], 0.1)
        for f in findings
    )
    prob = round(min(1.0, max(0.0, penalty)), 2)

    return {
        "events": len(events),
        "duration_s": round(duration, 3),
        "event_rate": round(rate, 2),
        "robot_probability": prob,
        "verdict": "robotic" if prob >= 0.6 else ("suspicious" if prob >= 0.3 else "human-like"),
        "metrics": {
            "timing_cv": round(cv, 3),
            "mouse_straightness": straight,
            "mouse_points": len(moves),
        },
        "findings": findings,
    }
