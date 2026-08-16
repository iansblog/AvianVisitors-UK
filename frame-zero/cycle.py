#!/usr/bin/env python3
"""AvianVisitors frame-zero client: cycle two server-rendered collages on a
Pimoroni Inky Impression 7.3" e-ink display driven by a Raspberry Pi Zero.

Every ``interval`` seconds it fetches the next window's collage afresh from the
BirdNET-Pi (``/all`` and ``/today`` by default) at the panel's native 800x480,
fits it to the panel, and pushes it to the Inky. The images are re-downloaded
each cycle, so the frame always tracks the current birds as the day rolls on.
Runs as a systemd service (see install.sh); ``--once`` and ``--preview`` let you
test on any machine without the panel attached.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import tomllib
import urllib.request

from PIL import Image

PANEL_W, PANEL_H = 800, 480  # Inky Impression 7.3" native landscape resolution
WINDOWS = ("1h", "12h", "24h", "7d", "today", "all")

DEFAULTS = {
    "base_url": "http://birdnet.local",
    "windows": ["all", "today"],   # cycled in this order
    "fetch_w": PANEL_W,            # the size requested from the server
    "fetch_h": PANEL_H,
    "width": PANEL_W,              # the panel's pixel size (fit crops if they differ)
    "height": PANEL_H,
    "interval": 300,               # seconds each image stays on the panel
    "saturation": 0.5,             # 7-ink palette blend: 0 muted .. 1 full colour
    "h_flip": False, "v_flip": False,
    "cs_pin": None, "dc_pin": None, "reset_pin": None, "busy_pin": None,
    "timeout": 60,
}


def load_config(path):
    cfg = dict(DEFAULTS)
    if path:
        with open(os.path.expanduser(path), "rb") as f:
            cfg.update(tomllib.load(f))
    cfg["windows"] = [str(w).lower().strip() for w in cfg["windows"] if str(w).strip()]
    for w in cfg["windows"]:
        if w not in WINDOWS:
            raise SystemExit(f"windows must be a subset of {', '.join(WINDOWS)}, not {w!r}")
    if not cfg["windows"]:
        raise SystemExit("windows must list at least one collage, e.g. ['all', 'today']")
    for key in ("fetch_w", "fetch_h", "width", "height", "interval", "timeout"):
        cfg[key] = int(cfg[key])
    cfg["saturation"] = float(cfg["saturation"])
    cfg["h_flip"] = bool(cfg["h_flip"])
    cfg["v_flip"] = bool(cfg["v_flip"])
    for key in ("cs_pin", "dc_pin", "reset_pin", "busy_pin"):
        v = cfg[key]
        cfg[key] = int(v) if v not in (None, "", 0) else None
    return cfg


def collage_url(cfg, window):
    """The short-URL form the BirdNET-Pi serves (/all, /today, /1h, ...)."""
    return (f"{cfg['base_url'].rstrip('/')}/{window}"
            f"?orientation=landscape&w={cfg['fetch_w']}&h={cfg['fetch_h']}")


def fetch_image(cfg, window):
    url = collage_url(cfg, window)
    req = urllib.request.Request(url, headers={"User-Agent": "AvianVisitors-frame-zero/1.0"})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        data = r.read(20_000_000)
    return Image.open(io.BytesIO(data)).convert("RGB")


def fit(img, width, height):
    """Cover-fit to the panel: centre-crop to the panel aspect, then downscale.
    A no-op when the image already matches the panel aspect (the server renders
    the collage natively at 800x480, so in normal use nothing is cropped)."""
    target = width / height
    ar = img.width / img.height
    if ar > target:                       # too wide: trim the sides
        nw = round(img.height * target)
        x0 = (img.width - nw) // 2
        img = img.crop((x0, 0, x0 + nw, img.height))
    elif ar < target:                     # too tall: trim top and bottom
        nh = round(img.width / target)
        y0 = (img.height - nh) // 2
        img = img.crop((0, y0, img.width, y0 + nh))
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return img


def open_panel(cfg):
    """Return a configured Inky Impression 7.3" driver. Lazy import so this
    module loads (and --preview works) on a machine without the panel library."""
    from inky.auto import auto
    if any(cfg[k] is not None for k in ("cs_pin", "dc_pin", "reset_pin", "busy_pin")):
        from inky.inky_ac073tc1a import Inky
        return Inky(resolution=(cfg["width"], cfg["height"]),
                    cs_pin=cfg["cs_pin"] or 8, dc_pin=cfg["dc_pin"] or 22,
                    reset_pin=cfg["reset_pin"] or 27, busy_pin=cfg["busy_pin"] or 17,
                    h_flip=cfg["h_flip"], v_flip=cfg["v_flip"])
    return auto()


def push(panel, img, cfg):
    panel.set_image(img, saturation=cfg["saturation"])
    panel.show()


def cycle(cfg, once=False, preview=None):
    if preview:
        img = fit(fetch_image(cfg, cfg["windows"][0]), cfg["width"], cfg["height"])
        img.save(preview)
        print(f"wrote preview {preview}")
        return
    while True:
        for window in cfg["windows"]:
            t0 = time.time()
            try:
                panel = open_panel(cfg)
                img = fit(fetch_image(cfg, window), cfg["width"], cfg["height"])
                push(panel, img, cfg)
                print(f"{time.strftime('%H:%M:%S')} shown {window}")
            except Exception as e:
                # Keep the last image on the panel and try again next cycle.
                print(f"{time.strftime('%H:%M:%S')} {window} failed: {e}", file=sys.stderr)
            if once:
                continue  # run the whole pass without waiting between windows
            wait = cfg["interval"] - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
        if once:
            return


def main():
    ap = argparse.ArgumentParser(description="Cycle the BirdNET-Pi collages on an Inky Impression 7.3.")
    ap.add_argument("--config", help="path to config.toml (defaults are fine for most installs)")
    ap.add_argument("--base-url", help="override base_url, e.g. http://birdnet.local")
    ap.add_argument("--interval", type=int, help="override the seconds each image stays up")
    ap.add_argument("--windows", help="override the window order, e.g. all,today")
    ap.add_argument("--once", action="store_true", help="run one pass through the windows, then exit")
    ap.add_argument("--preview", help="write the first window, fitted to the panel, as a PNG (no panel needed)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.base_url:
        cfg["base_url"] = args.base_url
    if args.interval:
        cfg["interval"] = args.interval
    if args.windows:
        cfg["windows"] = [w.strip() for w in args.windows.split(",") if w.strip()]
        for w in cfg["windows"]:
            if w not in WINDOWS:
                raise SystemExit(f"windows must be a subset of {', '.join(WINDOWS)}, not {w!r}")
    cycle(cfg, once=args.once, preview=args.preview)


if __name__ == "__main__":
    main()
