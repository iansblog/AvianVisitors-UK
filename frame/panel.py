#!/usr/bin/env python3
"""Generic e-ink client: fetch the server-rendered collage and push it to the panel.

The server renders the collage the browser draws as a plain PNG, at any size
(avian/api/frame.php -> avian/scripts/render_collage.py). Because the collage
layout adapts to any aspect, this client simply requests the panel's native
resolution - no cropping - then quantises to the panel's ink palette and hands
the image to whatever drives the hardware.

Works for any e-ink display:
  - size:        set width/height to the panel's native pixels
                 (e.g. 800x480 Inky Impression 7.3", 400x300 B/W/R, 152x152…)
  - colours:     inks lists the panel's palette; order doesn't matter
                 (mono = 2 inks, B/W/R = 3, Spectra-6 7-colour = 6, …)
  - hardware:    set push_command; your own firmware/script is run with the
                 {image} path (and {width}/{height}) so it does the write.
                 If you leave push_command out, the quantised PNG is dropped in
                 cache/panel.png for your firmware to pick up instead.

Runs on a timer (see systemd/birdpanel.*). Skips the refresh - sparing the
panel's cycle budget - when the detected species/count-brackets haven't changed,
in quiet hours, or when the image is byte-identical to the last push.
``--preview out.png`` writes the quantised PNG anywhere, so the look can be
checked on a machine with no panel.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

from PIL import Image

import display  # reuse fetch_recent/signature/state helpers from the frame client

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

# Default palette: Inky Impression 7.3" Spectra-6. Config can override with any
# list of RGB inks (2 = mono, 3 = B/W/R, 4 = Spectra-4, …).
SPECTRA6 = [(236, 234, 223), (26, 26, 28), (165, 60, 56),
            (198, 176, 74), (49, 71, 130), (58, 110, 72)]

DEFAULTS = {
    "base_url": "http://birdnet.local",
    "window": "",               # "" = legacy hours=24; else one of 1h/12h/24h/7d/today/all
    "hours": 24,
    "orientation": "",          # ""/landscape = 800x480, portrait = 480x800 (when width/height unset)
    "width": 800,
    "height": 480,
    "inks": SPECTRA6,
    "push_command": "",     # e.g. "sudo ~/my-firmware --image {image}" ; "" = file drop
    "quiet_start": 0, "quiet_end": 0,
    "heal_hours": 24,
    "state": "~/.birdframe/panel-state.json",
    "cache": "~/.birdframe",
    "timeout": 45,
    "basic_user": None, "basic_pass": None,
}

WINDOWS = ("1h", "12h", "24h", "7d", "today", "all")


def load_config(path):
    cfg = dict(DEFAULTS)
    explicit = {}
    if path:
        with open(os.path.expanduser(path), "rb") as f:
            data = tomllib.load(f)
        explicit = {k: v for k, v in data.items() if k in ("width", "height")}
        cfg.update(data)
    cfg["inks"] = [tuple(ink) for ink in cfg["inks"]]
    orient = (cfg.get("orientation") or "").lower().strip()
    if orient not in ("", "portrait", "landscape"):
        raise SystemExit(f"orientation must be portrait or landscape, not {cfg['orientation']!r}")
    if orient == "portrait":
        if "width" not in explicit:
            cfg["width"] = 480
        if "height" not in explicit:
            cfg["height"] = 800
    cfg["_explicit"] = set(explicit)
    cfg["width"] = int(cfg["width"])
    cfg["height"] = int(cfg["height"])
    if cfg["window"] and cfg["window"].lower() not in WINDOWS:
        raise SystemExit(f"window must be one of {', '.join(WINDOWS)}, not {cfg['window']!r}")
    cfg["window"] = cfg["window"].lower()
    return cfg


def fetch_image(cfg, auth):
    # A named window fetches the server-rendered collage through its short URL
    # (/today, /7d, ...). The default stays the frame.php hours endpoint.
    if cfg["window"]:
        url = (f"{cfg['base_url'].rstrip('/')}/{cfg['window']}"
               f"?w={cfg['width']}&h={cfg['height']}")
    else:
        url = (f"{cfg['base_url'].rstrip('/')}/avian/api/frame.php"
               f"?w={cfg['width']}&h={cfg['height']}&hours={cfg['hours']}")
    req = urllib.request.Request(url, headers={"User-Agent": "AvianVisitors-panel/1.0"})
    if auth:
        req.add_header("Authorization", auth)
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        return Image.open(__import__("io").BytesIO(r.read(20_000_000))).convert("RGB")


def fit_panel(img, width, height):
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return img


def quantize(img, inks):
    """Floyd-Steinberg-dither to the panel's ink palette. Order-independent:
    Image.quantize matches to nearest palette entry, so any ink order works."""
    pal = Image.new("P", (1, 1))
    flat = [c for ink in inks for c in ink]
    flat += list(inks[0]) * ((768 - len(flat)) // 3)  # pad the 256-entry palette with the first ink
    pal.putpalette(flat[:768])
    return img.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")


def run(cfg, preview=None, force=False):
    now = time.time()
    state = display.load_state(cfg["state"])
    auth = display._auth(cfg)

    sig = None
    try:
        species = display.fetch_recent(cfg["base_url"], cfg["hours"], cfg["timeout"], auth,
                                       today=cfg["window"] == "today")
        sig = display.signature(species)
    except Exception as e:
        print(f"signature fetch failed: {e}", file=sys.stderr)  # treat as no change
    heal_due = now - state.get("last_refresh", 0) >= cfg["heal_hours"] * 3600
    changed = sig is not None and sig != state.get("signature")

    if not force and not preview:
        if display.in_quiet_hours(cfg, datetime.now().hour):
            print("quiet hours; skip")
            return
        if not changed and not heal_due:
            print("no change; skip")
            return
        print("refresh:", "changed" if changed else "heal")

    try:
        img = fit_panel(fetch_image(cfg, auth), cfg["width"], cfg["height"])
    except Exception as e:
        print(f"could not fetch image: {e}", file=sys.stderr)  # keep last panel image
        return
    out = quantize(img, cfg["inks"])

    if preview:
        out.save(preview)
        print(f"wrote preview {preview}")
        return

    cache_dir = os.path.expanduser(cfg["cache"])
    os.makedirs(cache_dir, exist_ok=True)
    panel_img = os.path.join(cache_dir, "panel.png")
    tmp = panel_img + ".tmp"
    out.save(tmp, format="PNG")
    os.replace(tmp, panel_img)  # atomic: a power cut can't leave a half-written image

    # Byte-identical to the last push? The panel already shows it; don't burn a
    # refresh cycle (and wear on the ink) on a no-op.
    if not force:
        prev_sig = state.get("signature")
        if sig == prev_sig and prev_sig is not None and not heal_due:
            # signature unchanged means the species/count-bracket set is the same,
            # but the layout is deterministic, so the image is too: skip the push.
            print("image unchanged; skip push")
            return

    if cfg["push_command"]:
        cmd = cfg["push_command"].replace("{image}", panel_img)
        cmd = cmd.replace("{width}", str(cfg["width"])).replace("{height}", str(cfg["height"]))
        try:
            subprocess.run(cmd, shell=True, check=True, timeout=cfg["timeout"])
        except Exception as e:
            print(f"push_command failed: {e}", file=sys.stderr)
            return
        display.save_state(cfg["state"], sig, now)
        print("panel updated")
    else:
        display.save_state(cfg["state"], sig, now)
        print(f"wrote {panel_img} (set push_command in config to drive the panel)")


def main():
    ap = argparse.ArgumentParser(description="Fetch the server-rendered collage and push it to an e-ink panel.")
    ap.add_argument("--config")
    ap.add_argument("--base-url")
    ap.add_argument("--window", help="one of 1h/12h/24h/7d/today/all (short collage URL)")
    ap.add_argument("--orientation", help="portrait or landscape (default size when width/height unset)")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--hours", type=int)
    ap.add_argument("--preview", help="write a quantised preview PNG instead of pushing")
    ap.add_argument("--force", action="store_true", help="refresh even if unchanged")
    args = ap.parse_args()

    cfg = load_config(args.config)
    explicit = set(cfg.get("_explicit", ()))
    for key in ("base_url", "window", "hours", "width", "height", "orientation"):
        val = getattr(args, key)
        if val:
            cfg[key] = val
            if key in ("width", "height"):
                explicit.add(key)
    if cfg["window"] and cfg["window"].lower() not in WINDOWS:
        raise SystemExit(f"window must be one of {', '.join(WINDOWS)}, not {cfg['window']!r}")
    cfg["window"] = cfg["window"].lower()
    orient = (cfg.get("orientation") or "").lower().strip()
    if orient not in ("", "portrait", "landscape"):
        raise SystemExit(f"orientation must be portrait or landscape, not {cfg['orientation']!r}")
    if orient == "portrait":
        if "width" not in explicit:
            cfg["width"] = 480
        if "height" not in explicit:
            cfg["height"] = 800
    run(cfg, preview=args.preview, force=args.force)


if __name__ == "__main__":
    main()
