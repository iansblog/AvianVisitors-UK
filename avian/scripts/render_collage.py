#!/usr/bin/env python3
"""Server-side AvianVisitors collage renderer (Pillow port of apt.js).

Renders the same nesting collage the site draws in the browser, entirely in
Python, so any display (e-ink panels included) can fetch a ready-made PNG at
any resolution. Reads the species list straight from the BirdNET-Pi SQLite DB
(the same query as the `recent` API), the silhouette masks/dims shipped in
avian/frontend/, and the bird cutouts in avian/assets/illustrations/.

Layout is a faithful port of avian/frontend/apt.js:
  tuning() budget + count-weighting (apt.js:227)
  maskPack() raster-mask nester (apt.js:290)
  scale-to-fit + re-centre (apt.js:520-556)
The only differences are: a deterministic per-species-set seed (stable image
between refreshes) and no browser/DOM - birds are composited with Pillow.

Usage:
  avian/scripts/.venv/bin/python render_collage.py \
      --width 800 --height 480 --hours 24 --out /tmp/frame.png
  avian/scripts/.venv/bin/python render_collage.py \
      --width 800 --height 480 --today --out /tmp/today.png
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import sys

import numpy as np
from PIL import Image

FLY_PROB = 0.15    # chance a bird shows in its flight pose (matches apt.js)
GRID_STRIDE = 4    # viewport px per occupancy cell (matches apt.js)
PAPER = (252, 252, 251)  # light-theme --paper from styles.css
FILL_BIAS = 1.645  # fill-mode ellipse scale (geometric mean of x/y bias)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
re_keep = re.compile(r"[^a-z0-9]+")

_masks: dict | None = None
_dims: dict | None = None


def masks() -> dict:
    global _masks
    if _masks is None:
        _dims, _masks = load_tables()
    return _masks


def dims() -> dict:
    global _dims
    if _dims is None:
        _dims, _masks = load_tables()
    return _dims


# --- data -------------------------------------------------------------------
def slugify(sci: str) -> str:
    return re_keep.sub("-", sci.lower()).strip("-")


def _bucket(n: int) -> int:
    for i, edge in enumerate((1, 2, 5, 15, 40, 100, 300, 1000)):
        if n <= edge:
            return i
    return 8


def seed_for(species: list[dict]) -> int:
    """Deterministic layout seed from the species set, so an unchanged set
    renders an identical image (stable mtime, no panel flicker)."""
    h = hashlib.sha256()
    for s in sorted((slugify(x["sci"]), _bucket(int(x.get("n") or 1))) for x in species):
        h.update(("%s:%d;" % s).encode())
    return int.from_bytes(h.digest(), "big") % 2147483647


class RNG:
    """Lehmer PRNG - the exact generator apt.js uses for maskPack noise."""

    def __init__(self, seed: int):
        self.seed = (int(seed) % 2147483647) or 1

    def next(self) -> float:
        self.seed = (self.seed * 16807) % 2147483647
        return self.seed / 2147483647


def load_tables() -> tuple[dict, dict]:
    """Current DIMS/MASKS. The standalone masks.json/dims.json are stale
    (249 entries, no flight poses), so read apt.js's inlined tables - the same
    single source of truth the browser uses (build_masks.py patches them)."""
    src_path = os.path.join(ROOT, "avian", "frontend", "apt.js")
    try:
        with open(src_path) as fh:
            src = fh.read()
        dims_raw = re.search(r"var DIMS = (\{.*?\});", src, re.S).group(1)
        masks_raw = re.search(r"var MASKS = (\{.*?\});", src, re.S).group(1)
        dims = {k: (float(v[0]), float(v[1])) for k, v in json.loads(dims_raw).items()}
        masks = {}
        for slug, rec in json.loads(masks_raw).items():
            w, h = int(rec["w"]), int(rec["h"])
            bits = np.frombuffer(base64.b64decode(rec["bits"]), dtype=np.uint8)
            masks[slug] = np.unpackbits(bits)[: w * h].reshape(h, w).astype(bool)
        return dims, masks
    except Exception:
        # Fall back to the (possibly stale) standalone JSON files.
        return (load_dims(os.path.join(ROOT, "avian", "frontend", "dims.json")),
                load_masks(os.path.join(ROOT, "avian", "frontend", "masks.json")))


def load_masks(masks_path: str) -> dict:
    with open(masks_path) as f:
        raw = json.load(f)
    out = {}
    for slug, rec in raw.items():
        w, h = int(rec["w"]), int(rec["h"])
        bits = np.frombuffer(base64.b64decode(rec["bits"]), dtype=np.uint8)
        arr = np.unpackbits(bits)[: w * h].reshape(h, w).astype(bool)
        out[slug] = arr
    return out


def load_dims(dims_path: str) -> dict:
    with open(dims_path) as f:
        return {k: (float(v[0]), float(v[1])) for k, v in json.load(f).items()}


def recent_species(db_path: str, hours: int | None = None, today: bool = False) -> list[dict]:
    """Same rows/order as avian/api/birdnet-api.php?action=recent.

    `today=True` pins the window to the current local calendar day
    (00:00-23:59:59), matching the API's `&today=1`; otherwise a rolling
    window of `hours` (default 24)."""
    if today:
        where = "Date = DATE('now','localtime')"
        bind = {}
    else:
        hours = hours if hours is not None else 24
        where = ("(julianday('now','localtime') - julianday(Date || ' ' || Time)) * 24 <= :hrs")
        bind = {"hrs": hours}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT Sci_Name AS sci, Com_Name AS com, COUNT(*) AS n, "
            "       MAX(Date || ' ' || Time) AS last_seen "
            "FROM detections "
            f"WHERE {where} "
            "GROUP BY Sci_Name ORDER BY last_seen DESC",
            bind,
        )
        return [dict(zip(("sci", "com", "n", "last_seen"), row)) for row in cur.fetchall()]
    finally:
        conn.close()


# --- image resolution -------------------------------------------------------
def _resolve_image(slug: str) -> str | None:
    """cutout.php's local-file lookup chain, shortened to local steps only."""
    candidates = [
        os.path.join(ROOT, "avian", "assets", "illustrations", slug + ".png"),
        os.path.join(ROOT, "avian", "assets", "cutouts", slug + ".png"),
        os.path.join(os.path.expanduser("~"), "BirdSongs", "Extracted", "cutouts", slug + ".png"),
    ]
    for p in candidates:
        if os.path.isfile(p) and os.path.getsize(p) > 1024:
            return p
    return None


_IMG_CACHE: dict[str, Image.Image] = {}


def _load_image(path: str) -> Image.Image:
    img = _IMG_CACHE.get(path)
    if img is None:
        img = Image.open(path).convert("RGBA")
        _IMG_CACHE[path] = img
    return img


def _find_nest() -> Image.Image | None:
    for name in ("nest.png", "nest.webp"):
        p = os.path.join(ROOT, "avian", "frontend", name)
        if os.path.isfile(p):
            try:
                return Image.open(p).convert("RGBA")
            except Exception:
                pass
    return None


# --- ported layout (apt.js) --------------------------------------------------
def tuning(n: int) -> dict:
    return {
        "packingBudgetFrac": 0.46 if n <= 4 else 0.40 if n <= 12 else 0.34 if n <= 24 else 0.28,
        "countExp": 0.65,
        "minTileAreaFrac": 0.0100 if n <= 8 else 0.0075 if n <= 20 else 0.0055,
        "ellipseAspectBias": 2.1,
    }


def _dilate_box(a: np.ndarray, k: int) -> np.ndarray:
    """Box (cross-free full-neighbour) dilation by k cells, no wrap-around."""
    a = np.asarray(a, bool)
    for _ in range(k):
        p = np.pad(a, 1)
        a = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return a


def _kernel(t: dict, stride: int):
    """Placement-independent grid footprint for a tile. The JS maps each grid
    cell to the mask cell nearest its left edge; with a fixed grid origin the
    result differs only in edge cells (absorbed by the pad gap), so we compute
    it once per pack instead of per candidate position."""
    m = t["mask"]
    mh, mw = m.shape
    full_w, full_h = t["fullW"], t["fullH"]
    kw = max(1, math.ceil(full_w / stride))
    kh = max(1, math.ceil(full_h / stride))
    cols = np.floor(np.arange(kw) * stride * mw / full_w).astype(int)
    rows = np.floor(np.arange(kh) * stride * mh / full_h).astype(int)
    np.clip(cols, 0, mw - 1, out=cols)
    np.clip(rows, 0, mh - 1, out=rows)
    return m[np.ix_(rows, cols)].astype(np.uint8), kw, kh


def _collides(grid: np.ndarray, t: dict, px: float, py: float, stride: int) -> bool:
    fp, kw, kh = t["fp"], t["fpw"], t["fph"]
    gx0 = int(math.floor(px / stride))
    gy0 = int(math.floor(py / stride))
    if gx0 < 0 or gy0 < 0 or gx0 + kw > grid.shape[1] or gy0 + kh > grid.shape[0]:
        return True
    return bool(np.any(grid[gy0:gy0 + kh, gx0:gx0 + kw] & fp))


def _stamp(grid: np.ndarray, t: dict, px: float, py: float, pad: int, stride: int) -> None:
    fp, kw, kh = t["fp"], t["fpw"], t["fph"]
    gx0 = int(math.floor(px / stride))
    gy0 = int(math.floor(py / stride))
    if pad > 0:
        fp = _dilate_box(np.pad(fp, pad), pad)  # dilate into the pad ring
        gx0 -= pad
        gy0 -= pad
        kw += 2 * pad
        kh += 2 * pad
    gy0s, gx0s = max(0, gy0), max(0, gx0)
    gy1s = min(grid.shape[0], gy0 + kh)
    gx1s = min(grid.shape[1], gx0 + kw)
    grid[gy0s:gy1s, gx0s:gx1s] |= fp[gy0s - gy0:gy0s - gy0 + gy1s - gy0s,
                                      gx0s - gx0:gx0s - gx0 + gx1s - gx0s]


def mask_pack(tiles: list[dict], W: int, H: int, xbias: float, ybias: float,
              pad: int, rng: RNG, stride: int = GRID_STRIDE) -> list[dict]:
    """apt.js maskPack: occupancy grid + elliptical spiral, nearest fit."""
    GW = math.ceil(W / stride) + 2
    GH = math.ceil(H / stride) + 2
    grid = np.zeros((GH, GW), dtype=np.uint8)
    tiles.sort(key=lambda t: t["fullW"] * t["fullH"], reverse=True)
    for t in tiles:
        t["fp"], t["fpw"], t["fph"] = _kernel(t, stride)
    placed = []
    cx, cy = W / 2.0, H / 2.0

    for i, t in enumerate(tiles):
        if i == 0:
            t["x"], t["y"] = cx - t["fullW"] / 2, cy - t["fullH"] / 2
            _stamp(grid, t, t["x"], t["y"], pad, stride)
            placed.append(t)
            continue

        com_w = com_x = com_y = 0.0
        for p in placed:
            a = p["fullW"] * p["fullH"]
            com_x += (p["x"] + p["fullW"] / 2) * a
            com_y += (p["y"] + p["fullH"] / 2) * a
            com_w += a
        com_x /= com_w
        com_y /= com_w

        best = None
        best_cost = math.inf
        step = max(stride, min(t["fullW"], t["fullH"]) * 0.05)
        max_r = max(W, H)
        found_ring = -1
        phase = rng.next() * 2 * math.pi
        r = 0.0
        while r <= max_r:
            if found_ring >= 0 and r > found_ring + step * 2:
                break
            samples = max(36, int(r / 1.6))
            for k in range(samples):
                theta = phase + (k / samples) * 2 * math.pi
                px = cx + r * xbias * math.cos(theta) - t["fullW"] / 2
                py = cy + r * ybias * math.sin(theta) - t["fullH"] / 2
                if px < 0 or py < 0 or px + t["fullW"] > W or py + t["fullH"] > H:
                    continue
                if _collides(grid, t, px, py, stride):
                    continue
                dxx = px + t["fullW"] / 2 - com_x
                dyy = py + t["fullH"] / 2 - com_y
                cost = math.hypot(dxx / xbias, dyy / ybias) + rng.next() * step * 0.5
                if cost < best_cost:
                    best_cost = cost
                    best = (px, py)
            if best is not None and found_ring < 0:
                found_ring = r
            r += step
        if best is not None:
            t["x"], t["y"] = best
            _stamp(grid, t, best[0], best[1], pad, stride)
        else:
            t["x"], t["y"] = -99999.0, -99999.0
        placed.append(t)
    return placed


def cluster_bounds(placed: list[dict]) -> dict:
    L = R = T = B = None
    for t in placed:
        if t["x"] < -1000:
            continue
        if L is None or t["x"] < L:
            L = t["x"]
        if R is None or t["x"] + t["fullW"] > R:
            R = t["x"] + t["fullW"]
        if T is None or t["y"] < T:
            T = t["y"]
        if B is None or t["y"] + t["fullH"] > B:
            B = t["y"] + t["fullH"]
    return {"L": L or 0, "R": R or 0, "T": T or 0, "B": B or 0}


def _fit_loop(tiles: list[dict], W: int, H: int, xbias: float, ybias: float,
              pad: int, rng: RNG, stride: int) -> tuple[list[dict], dict]:
    """apt.js scale-to-fit: shrink + repack until every tile lands on-screen.
    Returns the placed tiles and their bounding box."""
    placed = mask_pack(tiles, W, H, xbias, ybias, pad, rng, stride)
    b = cluster_bounds(placed)
    for _ in range(10):
        missing = any(t["x"] < -1000 for t in placed)
        overflow = b["L"] < 0 or b["T"] < 0 or b["R"] > W or b["B"] > H
        if not missing and not overflow:
            break
        scale = 0.93
        if overflow:
            cl_w, cl_h = b["R"] - b["L"], b["B"] - b["T"]
            sx = (W * 0.96) / max(cl_w, W * 0.96)
            sy = (H * 0.94) / max(cl_h, H * 0.94)
            scale = min(scale, sx, sy)
        for t in tiles:
            t["fullW"] *= scale
            t["fullH"] *= scale
        placed = mask_pack(tiles, W, H, xbias, ybias, pad, rng, stride)
        b = cluster_bounds(placed)
    return placed, b


def layout(items: list[dict], W: int, H: int, *,
           count_exp: float | None = None, xbias: float | None = None,
           ybias: float | None = None, pad: int | None = None, floor: float = 0.0,
           fill: float = 0.0, seed: int | None = None,
           stride: int = GRID_STRIDE, rng: RNG | None = None) -> list[dict] | None:
    """The apt.js layout half of render(): tile sizing + nesting + recentre.

    `fill` (0..1) zooms the whole cluster up so its bounding box spans that
    fraction of the viewport, after the budget-based fit. The browser collage
    leaves a deliberately airy plate (the budget is ~28-46% of the viewport),
    which reads as wasted border on a large e-ink frame; the frame renderer
    uses fill=0.9 to scale the identical composition to the frame edges.

    Returns the placed tiles (each with x, y, fullW, fullH, slug, pose) or None
    when no species is drawable (caller shows the empty state instead)."""
    if rng is None:
        rng = RNG(seed if seed is not None else seed_for(items))
    T = tuning(len(items))
    if count_exp is None:
        count_exp = T["countExp"]
    if pad is None:
        pad = 1
    if xbias is None or ybias is None:
        portrait = H >= W
        if fill > 0:
            # Fill mode aims the cluster's ellipse at the canvas aspect
            # (xbias:ybias ~ W:H) so the zoom-to-fill step reaches the frame
            # edges in BOTH directions. The browser's 2.1:1 landscape bias
            # (or 0.83:1 portrait) leaves wide paper borders on a fixed frame.
            r = W / H
            xbias = FILL_BIAS * math.sqrt(r)
            ybias = FILL_BIAS / math.sqrt(r)
        else:
            xbias = 1.0 if portrait else T["ellipseAspectBias"]
            ybias = 1.2 if portrait else 1.0

    if floor > 0 and items:
        top = max((s.get("n") or 1) for s in items)
        fl = top * floor
        for s in items:
            if (s.get("n") or 1) < fl:
                s["n"] = max(1, round(fl))

    _dims, _masks = dims(), masks()
    tiles = []
    for s in items:
        base = slugify(s["sci"])
        pose = 1
        if base + "-2" in _dims and rng.next() < FLY_PROB:
            pose = 2
        slug = base + "-2" if pose == 2 else base
        mask = _masks.get(slug)
        if mask is None and pose == 2:
            pose, slug, mask = 1, base, _masks.get(base)
        if mask is None:
            continue
        d = _dims.get(slug)
        ar = d[0] / d[1] if d else 1.4
        n = int(s.get("n") or 1) or 1
        tiles.append({"sci": s["sci"], "slug": slug, "pose": pose,
                      "mask": mask, "ar": ar, "score": max(1, n) ** count_exp})

    if not tiles:
        return None

    vp_area = W * H
    budget = vp_area * T["packingBudgetFrac"]
    min_area = vp_area * T["minTileAreaFrac"]

    sum_score = sum(t["score"] for t in tiles) or 1
    for t in tiles:
        t["area"] = max(min_area, budget * t["score"] / sum_score)
    sum_a = sum(t["area"] for t in tiles)
    if sum_a > budget:
        fixed = sum(t["area"] for t in tiles if t["area"] <= min_area + 1e-9)
        flex = sum_a - fixed
        flex_budget = max(0, budget - fixed)
        shrink = min(1, flex_budget / flex) if flex > 0 else 1
        for t in tiles:
            if t["area"] > min_area + 1e-9:
                t["area"] *= shrink
    for t in tiles:
        t["fullW"] = math.sqrt(t["area"] * t["ar"])
        t["fullH"] = t["fullW"] / t["ar"]

    placed, b = _fit_loop(tiles, W, H, xbias, ybias, pad, rng, stride)

    if fill > 0:
        cl_w, cl_h = b["R"] - b["L"], b["B"] - b["T"]
        if cl_w > 0 and cl_h > 0:
            zoom = min(W * fill / cl_w, H * fill / cl_h)
            if zoom > 1.0:
                for t in tiles:
                    t["fullW"] *= zoom
                    t["fullH"] *= zoom
                # The zoomed plate is always on-screen (fill <= 1), but a
                # second fit loop keeps the same safety net if repacking
                # shifts the bbox slightly.
                placed, b = _fit_loop(tiles, W, H, xbias, ybias, pad, rng, stride)

    dx = W / 2 - (b["L"] + b["R"]) / 2
    dy = H / 2 - (b["T"] + b["B"]) / 2
    if abs(dx) > 1 or abs(dy) > 1:
        for t in placed:
            if t["x"] > -1000:
                t["x"] += dx
                t["y"] += dy
    return placed


def render(items: list[dict], W: int, H: int, *,
           count_exp: float | None = None, xbias: float | None = None,
           ybias: float | None = None, pad: int | None = None, floor: float = 0.0,
           fill: float = 0.0, seed: int | None = None, stride: int = GRID_STRIDE,
           paper=PAPER, rng: RNG | None = None) -> Image.Image:
    """Compose the collage for a W x H viewport and return a PIL image."""
    placed = layout(items, W, H, count_exp=count_exp, xbias=xbias, ybias=ybias,
                    pad=pad, floor=floor, fill=fill, seed=seed, stride=stride, rng=rng)
    if placed is None:
        return _render_empty(W, H, paper)

    img = Image.new("RGB", (W, H), paper)
    for t in placed:
        if t["x"] < -1000:
            continue
        src = _resolve_image(t["slug"])
        if src is None:
            continue
        tw, th = max(1, round(t["fullW"])), max(1, round(t["fullH"]))
        bird = _load_image(src).resize((tw, th), Image.LANCZOS)
        img.paste(bird, (round(t["x"]), round(t["y"])), bird)
    return img


def _render_empty(W: int, H: int, paper=PAPER) -> Image.Image:
    img = Image.new("RGB", (W, H), paper)
    nest = _find_nest()
    if nest is not None:
        s = min(W, H) * 0.55 / max(nest.size)
        nw, nh = max(1, round(nest.width * s)), max(1, round(nest.height * s))
        nest = nest.resize((nw, nh), Image.LANCZOS)
        img.paste(nest, ((W - nw) // 2, (H - nh) // 2), nest)
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the AvianVisitors collage to a PNG.")
    ap.add_argument("--out", required=True, help="output PNG path (written atomically)")
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--today", action="store_true",
                    help="calendar day (00:00-23:59 local) instead of a rolling hours window")
    ap.add_argument("--db", default=os.path.join(ROOT, "scripts", "birds.db"))
    ap.add_argument("--count-exp", type=float, default=None,
                    help="count-to-size exponent (site default 0.65; lower = even hierarchy)")
    ap.add_argument("--xbias", type=float, default=None, help="cluster width bias")
    ap.add_argument("--ybias", type=float, default=None, help="cluster height bias")
    ap.add_argument("--pad", type=int, default=None, help="gap between birds in grid cells (default 1)")
    ap.add_argument("--floor", type=float, default=0.0,
                    help="0..1: floor rarest counts to this fraction of the max (0 = none)")
    ap.add_argument("--fill", type=float, default=0.9,
                    help="0..1: zoom the cluster so its bbox spans this fraction "
                         "of the viewport (0 = leave the browser-style airy plate; "
                         "0.9 = fill the frame edge-to-edge-ish)")
    ap.add_argument("--seed", type=int, default=None, help="override the deterministic seed")
    args = ap.parse_args()

    if args.width < 16 or args.height < 16:
        sys.exit("width/height too small")
    items = recent_species(args.db, args.hours, today=args.today)
    img = render(items, args.width, args.height,
                 count_exp=args.count_exp, xbias=args.xbias, ybias=args.ybias,
                 pad=args.pad, floor=args.floor, fill=args.fill, seed=args.seed)

    out = args.out
    tmp = out + ".tmp." + str(os.getpid())
    img.save(tmp, "PNG")
    os.replace(tmp, out)
    print(f"wrote {out} ({img.width}x{img.height}, {len(items)} species, "
          f"{sum(1 for i in items if masks().get(slugify(i['sci'])) is not None)} drawn)")


if __name__ == "__main__":
    main()
