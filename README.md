# AvianVisitors-UK

*A live bird collage for UK gardens, powered by BirdNET.*

An acoustic bird monitor for the Raspberry Pi that identifies UK birds in real time and displays them as a growing collage of Japanese kachō-e style illustrations. Built on [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi) with the [AvianVisitors](https://github.com/Twarner491/AvianVisitors) collage overlay.

<img alt="AvianVisitors-UK collage" src="docs/thumb.png" />

---

## What it does

- **Listens** via a USB microphone and identifies bird species using BirdNET machine learning
- **Displays** a live collage of detected birds as Edo-period Japanese woodblock style illustrations
- **Ships with 1245 bundled illustrations** (726 perched + 519 flight poses) covering common UK species
- **On-demand generation**: species without bundled illustrations get a new one generated automatically via free AI image APIs (no API key needed) — works on every supported board, since generation happens in the cloud
- **Runs offline** for all core BirdNET functionality — only the optional illustration generation needs internet

---

## Supported devices

| Device | RAM | BirdNET analysis | On-demand AI illustrations | Notes |
|--------|-----|------------------|----------------------------|-------|
| **Raspberry Pi 5** | 4–16 GB | Fast | **Enabled** | Recommended |
| **Raspberry Pi 4** (≥2 GB) | 2–8 GB | Fast | **Enabled** | Recommended |
| **Raspberry Pi 4** (1 GB) | 1 GB | Works | **Enabled** (rembg auto-skips) | zram + swap auto-enabled |
| **Raspberry Pi 3B / 3B+** | 1 GB | Slow but works | **Enabled** (rembg auto-skips) | zram + swap auto-enabled |
| **Raspberry Pi 3A+ / Zero 2W** | 512 MB–1 GB | Slow but works | **Enabled** (rembg auto-skips) | zram + swap auto-enabled |
| x86_64 PC / VM | any | Fast | **Enabled** | For testing, not a real deployment |

### Limitations

- **64-bit OS required** — 32-bit (armv7l) installs are not supported because
  there is no tflite wheel for 32-bit ARM on Python 3.10+. The installer
  detects this and tells you to reinstall with the 64-bit Raspberry Pi OS
  image (Pi 3, 4, and 5 all support it).
- **AI generation is cloud-side, so it works on every board** — free.ai does
  the rendering. Only the background removal (rembg) runs locally, and it
  auto-skips when free RAM drops below ~500 MB, serving the raw cream render
  instead. On 1 GB boards you may see renders with the cream background.
- **Pi 3 analysis speed**: the Cortex-A53 processes audio slower than
  real-time. Expect detection latency and occasional backlog on the busiest
  garden mornings; consider a shorter `RECORDING_LENGTH` if it falls behind.
- **On-demand generation needs internet** — everything else (detection,
  collage, web UI) runs fully offline.
- **Free tier rate limits** — free.ai and Wikipedia apply rate limits; the
  generator retries with exponential backoff, so first-time renders can take
  up to ~2 minutes.

---

## Requirements

| Qty | Item | Notes |
|-----|------|-------|
| 1 | Raspberry Pi (3, 4, or 5) — see [Supported devices](#supported-devices) | 64-bit OS required |
| 1 | Micro SD card (≥32 GB) | |
| 1 | USB lavalier microphone | Place in a window or mount outside |
| 1 | Pi power supply | |

Optional: an [eBird API key](https://ebird.org/api/keygen) to filter species by region.

---

## Pre-requisites

The installer must run as a **non-root user with passwordless sudo**. Your
login user (usually `pi`) already has this on stock Raspberry Pi OS. To check:

```bash
sudo -K && sudo -n true && echo "passwordless sudo OK"
```

If it prints nothing or errors, enable it with the Raspberry Pi config tool:

```bash
sudo raspi-config
```

Then navigate to **System Options → S10 Admin Password → Yes** to disable the
sudo password prompt. Selecting **Yes** answers "Would you like the admin
(sudo) password to be enabled?" with **No**, which installs a passwordless
sudo rule for your user.

To do it without the menu:

```bash
sudo raspi-config nonint do_sudo_pass 1
```

Log out and back in, then confirm the check above succeeds before installing.

---

## Quick install

```bash
ssh <your-username>@birdnet.local
curl -s https://raw.githubusercontent.com/iansblog/AvianVisitors-UK/main/newinstaller.sh | bash
```

This clones the repo, installs BirdNET-Pi, sets up all services, and reboots. Takes 20-40 minutes on a Pi 4.

After reboot:
- **Collage**: `http://birdnet.local/`
- **Admin UI**: `http://birdnet.local/index.php` (menu button → Settings, System, Logs)

---

## Illustrations

The repo ships with a curated set of UK bird illustrations in kachō-e style. To generate additional species or restyle the set:

```bash
# Install illustration tools
python3 -m venv ~/BirdNET-Pi/avian/scripts/.venv
~/BirdNET-Pi/avian/scripts/.venv/bin/pip install -r ~/BirdNET-Pi/avian/scripts/requirements.txt

# Generate illustrations for missing species
~/BirdNET-Pi/avian/scripts/.venv/bin/python3 ~/BirdNET-Pi/avian/scripts/generate_bird.py \
  "Erithacus rubecula" "European Robin" /tmp/robin.png

# Rebuild collage masks after adding new illustrations
python3 ~/BirdNET-Pi/avian/scripts/build_masks.py
```

See [`avian/scripts/README.md`](avian/scripts/README.md) for the full illustration pipeline.

---

## How the collage works

1. Each detection in BirdNET triggers a lookup for a bundled illustration
2. If no bundled illustration exists, the system checks for a cached background-removed photo
3. If nothing is cached, it fetches a Wikipedia photo and removes the background with rembg
4. As a final fallback, it generates a fresh kachō-e illustration via free.ai (no API key needed)
5. The result is cached for instant serving on future requests

Steps 3–4 are gated by `GENERATE_ILLUSTRATIONS` in `birdnet.conf` (enabled on
all boards; rembg skips itself when free RAM is low).

The collage JavaScript (`avian/frontend/apt.js`) lays out detected birds on a cream/dark paper background using the pose masks.

---

## Repo layout

```
avian/                  # UK illustration pipeline and collage
├── frontend/           # static HTML/JS/CSS for the collage
├── assets/             # 1245 bundled illustrations + photo-cutout fallbacks
├── api/                # PHP shims (cutout resolver, spectrogram, etc.)
├── scripts/            # illustration generation, mask building, prompt
└── forwarding/         # optional Home Assistant / MQTT / Cloudflare configs
frame/                  # optional e-ink wall display
scripts/                # BirdNET-Pi core scripts (analysis, recording, services)
model/                  # BirdNET model and species labels
templates/              # systemd service templates
```

Everything outside `avian/` and `frame/` is upstream BirdNET-Pi.

---

## Forwarding (optional)

See [`avian/forwarding/`](avian/forwarding/) for recipes to:
- Expose via **Cloudflare Tunnel** for a public HTTPS URL
- Publish detections to **Home Assistant** via REST sensor
- Bridge to **MQTT** for home automation

---

## Credits

This project builds on the work of several open-source projects:

- **[BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi)** by Patrick McGuire — the acoustic bird monitoring platform (CC-BY-NC-SA-4.0)
- **[AvianVisitors](https://github.com/Twarner491/AvianVisitors)** by Twarner491 — the live bird collage overlay
- **[BirdNET](https://github.com/kahst/BirdNET-Analyzer)** by Stefan Kahl — the bird sound classification framework (Cornell Lab of Ornithology)
- **[rembg](https://github.com/danielgatis/rembg)** — background removal for photo cutouts
- **[free.ai](https://api.free.ai)** — free SDXL image generation for on-demand illustrations

---

## License

CC-BY-NC-SA-4.0, inherited from [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi/blob/main/LICENSE). Non-commercial use only.

See [README.upstream.md](README.upstream.md) for the original BirdNET-Pi README.
