"""Human-like motion and timing helpers.

Không cố đạt "không thể phân biệt" — chỉ đủ để tránh pattern cơ bản
(timing hoàn toàn đều, đường thẳng tuyến tính, gõ phím tốc độ không đổi).
"""

from __future__ import annotations

import asyncio
import random


def bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 24,
    jitter: float = 3.0,
) -> list[tuple[float, float]]:
    """Cubic Bezier từ start → end, có nhiễu nhẹ ở control points."""
    if steps < 2:
        raise ValueError("steps must be >= 2")
    x0, y0 = start
    x3, y3 = end
    dx, dy = x3 - x0, y3 - y0

    c1 = (
        x0 + dx * 0.3 + random.uniform(-jitter, jitter),
        y0 + dy * 0.1 + random.uniform(-jitter, jitter),
    )
    c2 = (
        x0 + dx * 0.7 + random.uniform(-jitter, jitter),
        y0 + dy * 0.9 + random.uniform(-jitter, jitter),
    )

    pts: list[tuple[float, float]] = []
    for i in range(steps):
        t = i / (steps - 1)
        mt = 1 - t
        x = mt**3 * x0 + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * x3
        y = mt**3 * y0 + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * y3
        pts.append((round(x, 2), round(y, 2)))
    pts[-1] = (x3, y3)
    return pts


def human_delay(base: float = 0.25, spread: float = 0.4, low: float = 0.05) -> float:
    """Delay ngẫu nhiên lệch thiên về phía nhanh (như người thật)."""
    delay = base + random.expovariate(1.0 / max(spread, 1e-6)) * spread * 0.5
    return round(max(low, delay), 3)


def humanize_typing(text: str, base: float = 0.09, spread: float = 0.12) -> list[float]:
    """Per-char delay: chữ cái dài hơn thì gõ lâu hơn, có nghễu. Trả về list delay."""
    delays: list[float] = []
    for ch in text:
        weight = 1.0 + (0.5 if ch.isupper() else 0.0) + (0.4 if ch in ".,!?;:" else 0.0)
        delays.append(round(human_delay(base * weight, spread, low=0.02), 3))
    return delays


async def sleep_between(points: list[tuple[float, float]], speed: float = 1.0) -> float:
    """Sleep tổng thời gian mô phỏng di chuyển chuột theo các điểm Bezier."""
    total = 0.0
    for _ in points[:-1]:
        d = human_delay(0.012, 0.02, low=0.004) / max(speed, 0.1)
        total += d
        await asyncio.sleep(d)
    return round(total, 3)
