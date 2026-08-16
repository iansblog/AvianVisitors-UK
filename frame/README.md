# AvianVisitors e-ink frame

*The last 24h of birds, framed on the wall by your window.*

A [Pimoroni Inky Impression 13.3"](https://amzn.to/4xlAWr3) (Spectra 6) mirroring the live collage. A Pi screenshots the site, mats it onto an A5 opening, and pushes to the panel, refreshing only when the birds change. Build one of your own at [theodore.net/projects/AvianVisitors#frame-ous](https://theodore.net/projects/AvianVisitors/#frame-ous).

![](https://theodore.net/assets/images/AvianVisitors/final.jpg)

---

### BOM

| Qty | Description | Price | Link |
|-----|-------------|-------|------|
| 1 | Raspberry Pi 3 A+ or Zero 2 W | ~$25-35 | [Amazon](https://amzn.to/49Xp58I) |
| 1 | 13.3" E Ink Display     | $299.99 | [Amazon](https://amzn.to/4xlAWr3) |
| 1 | A4 Wood Photo Frame    | $21.99 | [Amazon](https://amzn.to/3RWFbJE) |
| 1 | Long, Flat Micro USB Cable    | $7.99 | [Amazon](https://a.co/d/0a59rKSk) |
| 1 | Flat USB Brick    | $7.59 | [Amazon](https://amzn.to/3S4CtSs) |
| | **Total** | **~$365** | | |

The 3 A+ and Zero 2 W are both tested and set up identically; any Pi with the 40-pin header that runs 64-bit Raspberry Pi OS works. The printed backing pressure-fits either board.

CAD + 3d print files can be found in [`hardware/`](hardware/).

### Kits

I offer the frame and the bird mic as separate electronics kits. I put up a store for some of my open-source projects and will soon be able to offer kits cheaper than buying all the components individually, once I start buying in bulk.

- [Frame kit](https://theodore.net/store/avian-visitors/)
- [Bird mic kit](https://theodore.net/store/avian-mic/)

---

## 1. Flash the SD card

Flash an sd card with Raspberry Pi OS Lite (64-bit) via [Raspberry Pi Imager](https://www.raspberrypi.com/software/). In the customisation dialog set:

- Username
- WiFi SSID + password
- Hostname: `birdpic`
- Enable SSH with password auth

Then install in Pi and power up.

## 2. Run the installer

```bash
ssh <your-username>@birdpic.local
sudo apt update && sudo apt install -y git
git clone https://github.com/Twarner491/AvianVisitors
cd AvianVisitors/frame
```

Pick how the frame gets its birds:

```bash
# Pair with your bird mic on the same network (birdnet.local). The default.
./install.sh

# No microphone: draw the collage from BirdWeather for any ZIP code.
./install.sh --bird-weather --zip 94107

# Bird mic hosted at a public URL: point the frame straight at it.
./install.sh --image-url https://bird.onethreenine.net/frame.png?k=YOUR_FRAME_KEY

# Any e-ink display, any size: fetch the collage the server already renders
# (/avian/api/frame.php) at the panel's native resolution. No browser needed.
./install.sh --panel --width 800 --height 480
```

Each one enables SPI + I2C, installs the deps and a systemd timer, writes `~/.birdframe/config.toml`, and reboots once to bring SPI up. Full options live in [`config.example.toml`](config.example.toml).

Panel mode is a different client (`panel.py`): instead of rendering here it fetches the PNG the server already rendered and quantises it to your panel's inks, then runs `push_command` (set in the config) with the image path so your own firmware drives the hardware. The collage layout adapts to any aspect, so set `width`/`height` to the panel's native pixels — 800x480 Inky Impression 7.3", 400x300 B/W/R, or anything else — and the inks to your palette (6 for Spectra-6, 3 for B/W/R, 2 for mono).

The panel can point at any of the same time slots the site picker offers. Each slot has a short URL that serves the finished collage at any size, e.g. `http://birdnet.local/today?w=800&h=480`, `/1h`, `/12h`, `/24h`, `/7d`, `/all` (a bare `/today` defaults to 800x480). Set `window = "today"` in the config to use one — the e-ink just shows the finished image and never renders anything itself. Leave `window` empty to keep using `/avian/api/frame.php?hours=24`.

#### Collage URLs

Request the finished PNG at your panel's native resolution (`?w=`/`?h=` clamp to 96–1600 px; beyond ~1600x1600 the height is scaled down to keep the render affordable). Any aspect works — the layout adapts. Common panels:

| Display | Native px | URL |
|---------|-----------|-----|
| 7.3" Spectra 6 (Inky Impression) | 800×480 | `/today?w=800&h=480` |
| 7.5" Waveshare (B/W or color) | 800×480 / 960×544 | `/today?w=960&h=544` |
| 13.3" HD (Inky Impression) | 1600×1200 | `/today?w=1600&h=1200` |
| 13.3" older | 960×680 | `/today?w=960&h=680` |
| B/W/R | 400×300 | `/today?w=400&h=300` |

The six time slots are `1h`, `12h`, `24h`, `7d` (rolling windows), `today` (current local calendar day 00:00–23:59:59) and `all` (the whole life list). Optional `exp`, `floor`, `pad`, `xbias`, `ybias` tunables are validated and clamped; the short URLs also take `?w=&h=`.

Portrait or landscape is automatic from the size you ask for, or pick an orientation and get a sensible default: `?orientation=portrait` serves 480x800, `?orientation=landscape` serves 800x480, and explicit `?w=`/`?h=` always win — e.g. `http://birdnet.local/today?orientation=portrait` for a vertical panel, or `http://birdnet.local/all?w=480&h=800`. The panel config and installer know the same trick: set `orientation = "portrait"` in the config (or `./install.sh --panel --orientation portrait`) and the width/height defaults flip; give an explicit `--width`/`--height` and they win.

#### How often it updates

Renders are cached on the server per slot + size, and the panel polls by just re-fetching the PNG. The cache re-renders only when the birds database changes — and never more often than every 2 minutes — so a poll every 1–2 minutes is cheap and a 15-minute poll costs nothing more. A new detection can trigger a fresh render almost immediately (the DB mtime gates it), so you're never more than one poll cycle behind, and bursts of requests for the same image are serialized so the server only ever renders once.

BirdWeather mode renders on the Pi from this repo's illustrations on GitHub, so there is no image set to copy over. ZIP codes with no station nearby fall back to the closest ones. If you are far from any BirdWeather station, add `--ebird-key <key>` (a free key from [ebird.org/api/keygen](https://ebird.org/api/keygen)) and the frame fills from eBird sightings instead.

The bundled illustrations center on the western U.S. If birds near your ZIP aren't in the set you cloned, the installer flags them and the frame skips them until they exist. To generate them, run [`generate_illustrations.py`](generate_illustrations.py) on a laptop or workstation (it uses the same rembg cutout as the rest of the pipeline, which the Pi can't fit in memory), passing your ZIP and a paid Google Gemini key, then commit the new cutouts or copy them to the Pi:

```bash
python3 generate_illustrations.py --zip 10001 --gemini-key YOUR_GEMINI_KEY
```

It generates only the species you're missing; `--country` and `--sample` carry through for non-US postcodes or a wider region.
