#!/usr/bin/env python3
"""Generate a kachō-e bird illustration via free.ai with retry logic.

Called by cutout.php as the final fallback when no bundled illustration,
cutout, or Wikipedia photo exists. Generates on cream background, removes
it with rembg, caches the result.

Usage:
    python3 generate_bird.py "Calypte anna" "Anna's Hummingbird" /path/to/output.png

Exit codes:
    0 - image generated and saved
    1 - generation failed after all retries
    2 - bad arguments
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

FREEAI_URL = "https://api.free.ai/v1/image/generate/"
USER_AGENT = "AvianVisitors/1.0"
MAX_RETRIES = 4
BACKOFF_BASE = 30.0       # generous backoff for rate limits
REQUEST_TIMEOUT = 120     # free.ai can be slow on SDXL
GENERATION_DELAY = 30     # minimum seconds between API calls (global)

PROMPT_TEMPLATE = """\
A perched {com_name} ({sci_name}) in the style of an Edo-period Japanese \
kachō-e woodblock print. The bird is rendered with VERY FEW MARKS. \
The body is essentially 2-4 flat color zones with sharp boundaries. \
Confident sumi-e ink linework with soft watercolor washes. \
Earthy palette: burnt umber, ochre, indigo, vermillion, muted greens. \
Eye, beak, and feet drawn with crisp ink.

The bird sits on a flat, uniform, warm cream background like aged Japanese \
mulberry paper. NO branch, NO twig, NO perch, NO leaves - ONLY the bird \
on the cream background.

The ENTIRE bird must fit within the frame with generous padding. \
EXACTLY TWO wings. EXACTLY TWO legs. EXACTLY ONE head. \
Both feet visible, small and delicate. No text, no signature."""


def slugify(sci: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', sci.lower()).strip('-')


def api_call(prompt: str) -> str | None:
    """Call free.ai API and return image URL, or None on failure."""
    body = json.dumps({"prompt": prompt, "model": "sdxl"}).encode()
    req = urllib.request.Request(
        FREEAI_URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        result = json.loads(r.read())
    return result.get("image_url")


def download_image(url: str) -> bytes:
    """Download image from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def remove_background(img_bytes: bytes) -> bytes | None:
    """Remove background using rembg u2netp. Returns PNG bytes or None."""
    try:
        from PIL import Image
        from rembg import new_session, remove

        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        session = new_session("u2netp")
        cut = remove(img, session=session)
        # Crop to bounding box + margin
        alpha = cut.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            pad = max(10, round(0.02 * max(bbox[2]-bbox[0], bbox[3]-bbox[1])))
            x0, y0 = max(0, bbox[0]-pad), max(0, bbox[1]-pad)
            x1, y1 = min(cut.width, bbox[2]+pad), min(cut.height, bbox[3]+pad)
            cut = cut.crop((x0, y0, x1, y1))

        # Resize to 800 max edge (matches cutout.php cache size)
        max_dim = max(cut.size)
        if max_dim > 800:
            scale = 800 / max_dim
            cut = cut.resize(
                (round(cut.width*scale), round(cut.height*scale)), Image.LANCZOS
            )

        buf = BytesIO()
        cut.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        error_log(f"rembg failed: {e}")
        return None


def error_log(msg: str):
    """Log to stderr for PHP error_log capture."""
    print(msg, file=sys.stderr)


def low_memory_mb(threshold_mb: int = 500) -> bool:
    """True when available RAM has dropped below threshold_mb (best-effort).

    rembg needs a few hundred MB on top of the running BirdNET services.
    If the board is nearly out of memory we skip rembg and serve the raw
    cream-background render instead - it still blends with the collage.
    """
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                    return avail_kb / 1024 < threshold_mb
    except (OSError, ValueError):
        pass
    return False


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: generate_bird.py <sci_name> <com_name> <output_path>", file=sys.stderr)
        return 2

    sci = sys.argv[1].strip()
    com = sys.argv[2].strip()
    out_path = Path(sys.argv[3])

    if not sci or not re.match(r'^[A-Za-z]+ [a-z]+', sci):
        error_log(f"invalid sci name: {sci}")
        return 2

    prompt = PROMPT_TEMPLATE.format(sci_name=sci, com_name=com)

    # Enforce minimum delay between API calls (lock file in /tmp,
    # user-scoped to avoid permission issues between www-data and pi).
    import tempfile
    lock_dir = tempfile.gettempdir()
    lock_path = Path(lock_dir) / f"avianvisitors_gen_{os.getuid()}.lock"
    if lock_path.exists():
        try:
            lock_age = time.time() - lock_path.stat().st_mtime
            if lock_age < GENERATION_DELAY:
                wait = GENERATION_DELAY - lock_age
                error_log(f"rate limit: waiting {wait:.0f}s for previous generation")
                time.sleep(wait)
        except OSError:
            pass

    # Create/update lock file (ignore failures - locking is best-effort)
    try:
        lock_path.write_text(f"{time.time()}\n")
    except OSError:
        pass

    backoff = BACKOFF_BASE
    image_url = None
    for attempt in range(MAX_RETRIES):
        try:
            image_url = api_call(prompt)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                retry_after = backoff
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = max(retry_after, float(ra))
                    except (TypeError, ValueError):
                        pass
                error_log(f"API {e.code}, retry {attempt+1}/{MAX_RETRIES} in {retry_after:.0f}s")
                time.sleep(retry_after)
                backoff *= 2
                continue
            error_log(f"API error {e.code}")
            return 1
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            if attempt < MAX_RETRIES - 1:
                error_log(f"API error ({e}), retry {attempt+1}/{MAX_RETRIES} in {backoff:.0f}s")
                time.sleep(backoff)
                backoff *= 2
                continue
            error_log(f"API error: {e}")
            return 1

    if not image_url:
        error_log("no image_url in API response")
        return 1

    # Download
    try:
        raw = download_image(image_url)
    except Exception as e:
        error_log(f"download failed: {e}")
        return 1

    if not raw or len(raw) < 1024:
        error_log(f"image too small ({len(raw) if raw else 0} bytes)")
        return 1

    # Remove background (skip on low memory to avoid OOM).
    if low_memory_mb():
        error_log("low memory: skipping rembg, serving raw render")
        try:
            from PIL import Image
            img = Image.open(BytesIO(raw)).convert("RGB")
            img.thumbnail((800, 800), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
        except Exception as e:
            error_log(f"could not normalize raw render: {e}")
            png_bytes = raw
    else:
        png_bytes = remove_background(raw)
        if not png_bytes:
            error_log("background removal failed")
            return 1

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    error_log(f"generated: {com} ({sci}) -> {out_path.name} ({len(png_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
