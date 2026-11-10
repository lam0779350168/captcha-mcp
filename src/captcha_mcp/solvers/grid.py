"""Dò lưới ô của image-grid captcha từ ảnh chụp — không cần đọc DOM trong iframe.

Nguyên tắc: ô trong lưới là các ảnh vuông ngăn cách bởi khe màu đồng nhất.
Ta dò theo cấu trúc thật của reCAPTCHA v2:

    ┌──────────────────────────┐
    │ header xanh (#1a73e8)    │  ← khối xanh đặc, rộng
    ├──────────────────────────┤
    │  ô  ô  ô                │  ← lưới: khe ngang + khe dọc
    │  ô  ô  ô                │
    ├──────────────────────────┤
    │ nút VERIFY (xanh đặc)   │  ← khối xanh đặc, nhỏ
    └──────────────────────────┘

Dò hàng bằng profile std (khe ngang có std ≈ 0), dò cột trên chính các hàng ô đó
(khe dọc tương tự). Nếu ảnh không có header/nút xanh → rơi về dò ô vuông-bận.
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


def _segments(profile: list[float], threshold: float, min_len: int = 4) -> list[tuple[int, int]]:
    """Các đoạn liên tiếp có profile > threshold (tức là không phải khe)."""
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


def _std_col(gray, x: int, y0: int, y1: int) -> float:
    px = gray.load()
    col = [px[x, y] for y in range(y0, y1)]
    m = sum(col) / len(col)
    return (sum((v - m) ** 2 for v in col) / len(col)) ** 0.5


def _std_row(gray, y: int, x0: int, x1: int) -> float:
    px = gray.load()
    row = [px[x, y] for x in range(x0, x1)]
    m = sum(row) / len(row)
    return (sum((v - m) ** 2 for v in row) / len(row)) ** 0.5


def _uniform_blue_blocks(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Các khối xanh **đặc** (header #1a73e8 và nút VERIFY của reCAPTCHA).

    Hai điều kiện cùng lúc:
      1. vùng xanh liền mạch (nút VERIFY chỉ chiếm ~30% bề rộng ảnh → ngưỡng phải thấp),
      2. màu **đồng nhất** trong khối (loại trời xanh/ảnh nhiễu có chút xanh lẻ).
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

    row_dense = [y for y in range(h) if sum(mask[y]) / max(w, 1) > 0.10]
    if not row_dense:
        return []
    bands: list[list[int]] = [[row_dense[0], row_dense[0]]]
    for y in row_dense[1:]:
        if y - bands[-1][1] <= 3:
            bands[-1][1] = y
        else:
            bands.append([y, y])

    blocks: list[tuple[int, int, int, int]] = []
    for y0, y1 in bands:
        bh = y1 - y0 + 1
        if bh < 10:
            continue
        cols = [x for x in range(w) if sum(mask[y][x] for y in range(y0, y1 + 1)) / bh > 0.5]
        if not cols:
            continue
        bx0, bx1 = cols[0], cols[-1]
        # đồng nhất màu? (mean color của khối phải khớp phần lớn pixel)
        tot = [0, 0, 0]
        cnt = 0
        for y in range(y0, y1 + 1):
            for x in range(bx0, bx1 + 1):
                c = px[x, y]
                tot[0] += c[0]
                tot[1] += c[1]
                tot[2] += c[2]
                cnt += 1
        if not cnt:
            continue
        mean = [v / cnt for v in tot]
        same = sum(
            1
            for y in range(y0, y1 + 1)
            for x in range(bx0, bx1 + 1)
            if abs(px[x, y][0] - mean[0]) < 30
            and abs(px[x, y][1] - mean[1]) < 30
            and abs(px[x, y][2] - mean[2]) < 30
        )
        if same / cnt < 0.6:
            continue
        blocks.append((bx0, y0, bx1, y1))
    return blocks


def find_blue_button(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Nút VERIFY: khối xanh đặc, **không phải** header (header rộng > 60% ảnh)."""
    w = img.size[0]
    blocks = _uniform_blue_blocks(img)
    best = None
    for b in blocks:
        if (b[2] - b[0]) >= w * 0.6:
            continue  # header
        if best is None or b[1] > best[1]:
            best = b
    return best


def _pick_uniform_group(segs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Giữ nhóm segment liên tiếp có chiều cao tương đương nhất (≥2 segment).

    Các hàng của lưới có cùng chiều cao; footer/icon bên dưới khác → bị loại.
    """
    if len(segs) <= 2:
        return segs
    heights = [b - a + 1 for a, b in segs]
    best: list[tuple[int, int]] = []
    best_score = 0.0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            group = list(range(i, j + 1))
            hs = [heights[k] for k in group]
            spread = max(hs) / max(min(hs), 1)
            score = len(group) / max(spread, 1.01)
            if score > best_score:
                best_score = score
                best = [segs[k] for k in group]
    return best or segs


def _grid_by_structure(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Dò lưới theo cấu trúc reCAPTCHA: header xanh → lưới ô → nút VERIFY."""
    w, h = img.size
    blocks = _uniform_blue_blocks(img)
    header = next((b for b in blocks if (b[2] - b[0]) > w * 0.6), None)
    button = None
    for b in blocks:
        if b is header:
            continue
        if button is None or b[1] > button[1]:
            button = b

    top = 0
    bottom = h
    if header and (header[2] - header[0]) > w * 0.6:
        top = header[3] + 2
    if button:
        bottom = button[1] - 2
    if bottom - top < 60:
        return []

    gray = img.convert("L")
    row_prof = [_std_row(gray, y, 0, w) for y in range(top, bottom)]
    if not row_prof:
        return []
    thr_r = max(3.0, 0.30 * max(row_prof))
    row_segs = [(top + a, top + b) for a, b in _segments(row_prof, thr_r, min_len=8)]
    if len(row_segs) < 2:
        return []
    rows = _pick_uniform_group(row_segs)
    if len(rows) < 2:
        return []

    bands = [(a, min(b + 1, h)) for a, b in rows]
    col_prof = [sum(_std_col(gray, x, a, b) for a, b in bands) / len(bands) for x in range(w)]
    thr_c = max(3.0, 0.30 * max(col_prof))
    col_segs = _segments(col_prof, thr_c, min_len=8)
    if len(col_segs) < 2:
        return []

    boxes: list[tuple[int, int, int, int]] = []
    for ry0, ry1 in rows:
        for cx0, cx1 in col_segs:
            boxes.append((cx0, ry0, cx1, ry1))
    return boxes


def _grid_by_shape(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Dự phòng: dò các ô VUÔNG và BẬN rồi giữ nhóm thống trị."""
    act = _activity_map(img)
    h = len(act)
    w = len(act[0]) if h else 0
    if not h or not w:
        return []

    row_prof = []
    for y in range(h):
        hits = sum(1 for v in act[y] if v >= GRADIENT_THRESHOLD)
        row_prof.append(hits / max(w, 1))
    col_prof = []
    for x in range(w):
        hits = sum(1 for y in range(h) if act[y][x] >= GRADIENT_THRESHOLD)
        col_prof.append(hits / max(h, 1))

    rows = _segments(row_prof, max(0.05, 0.30 * max(row_prof)), min_len=8)
    cols = _segments(col_prof, max(0.03, 0.20 * max(col_prof)), min_len=8)
    if not rows or not cols:
        return []

    def busy(x0: int, y0: int, x1: int, y1: int) -> float:
        tot = cnt = 0
        for y in range(y0, min(y1 + 1, h)):
            row = act[y]
            for x in range(x0, min(x1 + 1, w)):
                tot += 1 if row[x] >= GRADIENT_THRESHOLD else 0
                cnt += 1
        return tot / max(cnt, 1)

    candidates: list[tuple[int, int, int, int]] = []
    for ry0, ry1 in rows:
        for cx0, cx1 in cols:
            bw = cx1 - cx0 + 1
            bh = ry1 - ry0 + 1
            if bw < 24 or bh < 24:
                continue
            if not (0.65 <= bw / bh <= 1.55):
                continue
            if busy(cx0, ry0, cx1, ry1) < 0.08:
                continue
            candidates.append((cx0, ry0, cx1, ry1))

    if not candidates:
        return []
    groups: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for c in candidates:
        key = (round((c[2] - c[0] + 1) / 10), round((c[3] - c[1] + 1) / 10))
        groups.setdefault(key, []).append(c)
    best = max(groups.values(), key=len)
    if len(best) < 4:
        return []
    best.sort(key=lambda c: (c[1], c[0]))
    return best


def detect_grid(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Trả về các box ô (x0, y0, x1, y1), thứ tự hàng → cột."""
    boxes = _grid_by_structure(img)
    if len(boxes) >= 4:
        return boxes
    return _grid_by_shape(img)


def selected_tiles(img: Image.Image, boxes: list[tuple[int, int, int, int]]) -> set[int]:
    """Các ô đang được chọn (reCAPTCHA vẽ dấu tick xanh ở góc trên-trái của ô)."""
    rgb = img.convert("RGB")
    px = rgb.load()
    out: set[int] = set()
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        white = bluish = total = 0
        for y in range(y0, min(y0 + 34, rgb.size[1])):
            for x in range(x0, min(x0 + 34, rgb.size[0])):
                r, g, b = px[x, y]
                total += 1
                if r > 235 and g > 235 and b > 235:
                    white += 1
                if b > 170 and b - r > 45 and b - g > 15:
                    bluish += 1
        if not total:
            continue
        # ô đã chọn: có dấu tick trắng trên nền xanh nhạt (vừa phải, không phải trời xanh)
        if white / total > 0.02 and 0.01 < bluish / total < 0.6:
            out.add(i)
    return out


def header_bottom(img: Image.Image) -> int | None:
    """Đáy khối header xanh (nếu có) — dùng để click xuống dưới vùng bị che."""
    w = img.size[0]
    blocks = _uniform_blue_blocks(img)
    wide = [b for b in blocks if (b[2] - b[0]) > w * 0.6]
    if not wide:
        return None
    return max(b[3] for b in wide)


def filter_covered(img: Image.Image, boxes: list[tuple[int, int, int, int]]
                  ) -> list[tuple[int, int, int, int]]:
    """Loại các ô bị header xanh đè lên (không click được).

    Một số challenge hiện nội dung cuộn dưới header dính → hàng trên cùng bị che,
    click vào đó sẽ trúng header chứ không phải ô.
    """
    rgb = img.convert("RGB")
    px = rgb.load()
    kept: list[tuple[int, int, int, int]] = []
    for (x0, y0, x1, y1) in boxes:
        blue = total = 0
        for y in range(max(y0, 0), min(y1 + 1, rgb.size[1])):
            for x in range(max(x0, 0), min(x1 + 1, rgb.size[0])):
                r, g, b = px[x, y]
                total += 1
                if b > 140 and b - r > 40 and b - g > 20:
                    blue += 1
        if total and blue / total > 0.5:
            continue
        kept.append((x0, y0, x1, y1))
    return kept


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
