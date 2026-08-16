# frame-zero — Inky Impression 7.3" e-ink frame for a Pi Zero

A small client that turns a Pi Zero (V1.1, 32-bit Raspberry Pi OS "Trixie") plus
a Pimoroni Inky Impression 7.3" e-ink display into a bird-poster frame. It
fetches the **`/all`** and **`/today`** collages from your BirdNET-Pi afresh
every cycle and shows each for five minutes, so the frame always matches the
birds of the moment.

The images are requested from the BirdNET-Pi at the panel's native **800×480**,
so nothing is cropped (the server lays the collage out for that aspect, fills
the frame, and serves a plain PNG — `avian/api/frame.php`). The client covers
the network fetch, panel fitting, 7-ink quantisation and the Inky refresh.

## What you need

- Raspberry Pi Zero (any revision) with Raspberry Pi OS 32-bit installed,
  online, and your 40-pin GPIO header fitted.
- Pimoroni Inky Impression **7.3"** connected to the GPIO header.
- A BirdNET-Pi reachable on your network (the default `http://birdnet.local`).

## Install (one command on the Zero)

```bash
curl -sSL https://raw.githubusercontent.com/Twarner491/AvianVisitors/avian-visitors/frame-zero/install.sh -o /tmp/frame-zero-install.sh
bash /tmp/frame-zero-install.sh
```

The installer:

1. clones this repo (only the `frame-zero/` folder) into `~/avianvisitors-frame`,
2. enables SPI + I2C (`raspi-config`, plus `dtoverlay=i2c1`, `dtoverlay=spi0-0cs`),
3. installs the Inky drivers (`python3-gpiod`, `python3-spidev`, Pillow, numpy
   from apt — ARMv6-safe — and `gpiodevice`, `smbus2`, `inky` into a
   `--system-site-packages` venv),
4. writes `~/avianvisitors-frame/frame-zero/config.toml`,
5. installs and starts the `birdframe-zero` systemd service.

It reboots once at the end if SPI was just enabled (that's the one manual step
it can't avoid). After boot the frame takes over by itself.

### Options

```bash
bash /tmp/frame-zero-install.sh --base-url http://192.168.1.50   # your BirdNET-Pi's IP
bash /tmp/frame-zero-install.sh --interval 600                   # 10 min per image
bash /tmp/frame-zero-install.sh --no-reboot                      # reboot yourself later
```

## Config

Everything lives in `~/avianvisitors-frame/frame-zero/config.toml` (a commented
example is `config.example.toml` in this folder). After editing, restart with
`sudo systemctl restart birdframe-zero`. Things you might change:

- `base_url` — point at the BirdNET-Pi by IP if `.local` doesn't resolve.
- `windows` — the order of collages to cycle, e.g. `["today", "all"]` or a
  subset like `["24h", "today"]`. Any of `1h 12h 24h 7d today all`.
- `interval` — seconds each image stays up (default 300).
- `saturation` — 0 (muted) … 1 (full colour) for the 7-ink palette.
- `h_flip` / `v_flip` — if the panel is hung the other way up.
- `cs_pin` / `dc_pin` / `reset_pin` / `busy_pin` — only for pre-EEPROM 7.3"
  boards that the driver can't auto-detect (classic wiring: 8 / 24 / 25 / 17).

## Testing without a panel

On any machine with the repo cloned (no hardware needed):

```bash
python3 frame-zero/cycle.py --preview /tmp/all.png --base-url http://birdnet.local
```

writes the fitted 800×480 PNG so you can check the layout before touching the Pi.

## Troubleshooting

- **Blank panel after reboot** — SPI/I2C need a reboot to activate; run
  `ls /dev/spidev0.0` and `ls /dev/i2c-1`. If they're missing, reboot.
- **`No EEPROM detected!`** in `journalctl -u birdframe-zero` — your 7.3" is a
  pre-EEPROM board; uncomment the four `*_pin` lines in the config.
- **Image never updates** — `curl http://birdnet.local/all?w=800&h=480` on the
  Zero; if that fails, set `base_url` to the BirdNET-Pi's IP.
- **Frame hangs upside down** — set `v_flip = true` (or `h_flip`).
