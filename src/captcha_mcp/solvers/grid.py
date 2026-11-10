"""Dò lưới ô của image-grid captcha từ ảnh chụp — không cần đọc DOM trong iframe.

Nguyên tắc: ô trong lưới là vùng ảnh có **nhiều cạnh** (độ lệch pixel giữa các cột/hàng
liền kề), còn khe giữa các ô là vùng **đồng nhất** (không có cạnh nào).

Cách làm:
  1. tính "hoạt động" của từng pixel (so với lân cận phải/dưới),
  2. dựng profile theo hàng → tìm dải hàng chứa lưới (bỏ header/footer),
  3. trong dải đó, dựng profile theo cột → các khe (≈0 hoạt động) tách cột,
  4. lặp lại cho hàng → tách hàng.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

GRADIENT_THRESHOLD = 40  # |Δ| giữa hai pixel để coi là "cạnh"


def _activity_map(img: Image.Image) -> list[list[int]]:
    """Ma trận hoạt động (0-255) theo gradient ngang + dọc."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    act = [[0] * w for _ in range(h)]
    for y in range(h):
        row = act[y]
        for x in range(w):
            v = 0
            if x + 1 < w:
                v += abs(px[x, y] - px[x + 1, y])
            if y + 1 < h:
                v += abs(px[x, y] - px[x, y + 1])
            row[x] = min(255, v)
    return act


def _row_profile(act: list[list[int]], y0: int, y1: int) -> list[float]:
    """Tỉ lệ pixel 'có cạnh' theo từng hàng trong khoảng [y0, y1)."""
    out: list[float] = []
    for y in range(y0, y1):
        row = act[y]
        hits = sum(1 for v in row if v >= GRADIENT_THRESHOLD)
        out.append(hits / max(len(row), 1))
    return out


def _col_profile(act: list[list[int]], y0: int, y1: int) -> list[float]:
    if y1 <= y0:
        return []
    out: list[float] = []
    for x in range(len(act[0])):
        hits = sum(1 for y in range(y0, y1) if act[y][x] >= GRADIENT_THRESHOLD)
        out.append(hits / max(y1 - y0, 1))
    return out


def _segments(profile: list[float], threshold: float, min_len: int = 4) -> list[tuple[int, int]]:
    segs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(profile):
        if v > threshold:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                segs.append((start, i - 1))
            start = None
    if start is not None and len(profile) - start >= min_len:
        segs.append((start, len(profile) - 1))
    return segs


def detect_grid(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Trả về các box ô (x0, y0, x1, y1), thứ tự hàng → cột."""
    act = _activity_map(img)
    h = len(act)
    w = len(act[0]) if h else 0
    if not h or not w:
        return []

    # 1) dải hàng của lưới: các hàng "bận" nhất
    row_prof = _row_profile(act, 0, h)
    thr_row = max(0.06, 0.35 * max(row_prof))
    rows_full = _segments(row_prof, thr_row, min_len=8)
    if not rows_full:
        return []
    # gộp các dải gần nhau (lưới bị ngắt bởi khe hàng)
    merged: list[list[int]] = [list(rows_full[0])]
    for a, b in rows_full[1:]:
        if a - merged[-1][1] <= 12:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    band = max(merged, key=lambda s: s[1] - s[0])
    y0, y1 = band

    # 2) cột trong dải: khe = hoạt động ≈ 0
    col_prof = _col_profile(act, y0, y1 + 1)
    thr_col = max(0.02, 0.25 * max(col_prof))
    cols = _segments(col_prof, thr_col, min_len=6)
    if not cols:
        return []

    # 3) hàng trong dải
    row_prof2 = _row_profile(act, y0, y1 + 1)
    thr_row2 = max(0.06, 0.35 * max(row_prof2))
    rows = _segments(row_prof2, thr_row2, min_len=6)
    if not rows:
        return []

    boxes: list[tuple[int, int, int, int]] = []
    for ry0, ry1 in rows:
        for cx0, cx1 in cols:
            boxes.append((cx0, y0 + ry0, cx1, y0 + ry1))
    return boxes


def find_blue_button(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Tìm nút màu xanh đặc (nút VERIFY của reCAPTCHA là #1a73e8).

    Yêu cầu mật độ xanh cao trong khối (tránh ảnh nhiễu có chút xanh lẻ).
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    mask = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if b > 130 and b - r > 55 and b - g > 30:
                mask[y][x] = 1
    # dòng có mật độ xanh cao → dải nút
    row_dense = [y for y in range(h) if sum(mask[y]) / max(w, 1) > 0.25]
    if not row_dense:
        return None
    band_y0, band_y1 = row_dense[0], row_dense[-1]
    cols = [
        x
        for x in range(w)
        if sum(mask[y][x] for y in range(band_y0, band_y1 + 1)) / max(band_y1 - band_y0 + 1, 1)
        > 0.5
    ]
    if not cols:
        return None
    return (cols[0], band_y0, cols[-1], band_y1)


def draw_numbered(img: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    """Vẽ số thứ tự lên từng ô để AI đọc và trả lời theo số."""
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except OSError:
        font = None
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        d.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)
        cx, cy = x0 + 11, y0 + 11
        d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 0, 0))
        d.text((cx - 4, cy - 6), str(i), fill=(255, 255, 255), font=font)
    return out


def save_png(img: Image.Image, path: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path
