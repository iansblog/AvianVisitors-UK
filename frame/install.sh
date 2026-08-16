#!/usr/bin/env bash
# Install the AvianVisitors e-ink frame (display side) on a Raspberry Pi.
# Enables SPI + I2C, installs deps, makes a venv, installs the systemd timer.
#
# Four ways to feed the frame, pick one:
#   ./install.sh                            mirror the BirdNET-Pi on your network
#                                           (birdnet.local), rendered on this Pi
#   ./install.sh --image-url <URL>          fetch a ready-made frame PNG instead
#                                           (e.g. a public Cloudflare Worker)
#   ./install.sh --bird-weather --zip <ZIP> standalone from BirdWeather, no mic
#                                           (add --ebird-key <KEY> for remote ZIPs)
#   ./install.sh --panel --width 800 --height 480
#                                           fetch the collage from a BirdNET-Pi's
#                                           /avian/api/frame.php at the panel's
#                                           native size and push to any e-ink
#                                           display (via push_command; see the
#                                           generated config). Add
#                                           --window today for a calendar-day
#                                           slot served as a short URL (/today),
#                                           or --orientation portrait|landscape
#                                           for the matching default size.
set -euo pipefail
cd "$(dirname "$0")"
FRAME="$(pwd)"

MODE=local            # local | image | birdweather | panel
ZIP=""
IMAGE_URL=""
EBIRD_KEY=""
PANEL_W=""
PANEL_H=""
PANEL_WINDOW=""
PANEL_ORIENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bird-weather) MODE=birdweather; shift ;;
    --zip) [ $# -ge 2 ] || { echo "--zip needs a value, e.g. --zip 94107" >&2; exit 1; }
           ZIP="$2"; shift 2 ;;
    --zip=*) ZIP="${1#*=}"; shift ;;
    --image-url) [ $# -ge 2 ] || { echo "--image-url needs a value, e.g. --image-url https://bird.example/frame.png" >&2; exit 1; }
                 MODE=image; IMAGE_URL="$2"; shift 2 ;;
    --image-url=*) MODE=image; IMAGE_URL="${1#*=}"; shift ;;
    --ebird-key) [ $# -ge 2 ] || { echo "--ebird-key needs a value (a free key from ebird.org/api/keygen)" >&2; exit 1; }
                 EBIRD_KEY="$2"; shift 2 ;;
    --ebird-key=*) EBIRD_KEY="${1#*=}"; shift ;;
    --panel) MODE=panel; shift ;;
    --width) [ $# -ge 2 ] || { echo "--width needs a value in pixels" >&2; exit 1; }
             PANEL_W="$2"; shift 2 ;;
    --width=*) PANEL_W="${1#*=}"; shift ;;
    --height) [ $# -ge 2 ] || { echo "--height needs a value in pixels" >&2; exit 1; }
              PANEL_H="$2"; shift 2 ;;
    --height=*) PANEL_H="${1#*=}"; shift ;;
    --window) [ $# -ge 2 ] || { echo "--window needs a value: 1h 12h 24h 7d today all" >&2; exit 1; }
              MODE=panel; PANEL_WINDOW="$2"; shift 2 ;;
    --window=*) MODE=panel; PANEL_WINDOW="${1#*=}"; shift ;;
    --orientation) [ $# -ge 2 ] || { echo "--orientation needs a value: portrait or landscape" >&2; exit 1; }
              MODE=panel; PANEL_ORIENT="$2"; shift 2 ;;
    --orientation=*) MODE=panel; PANEL_ORIENT="${1#*=}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [ -n "$ZIP" ] && [ "$MODE" != birdweather ]; then
  echo "--zip only applies with --bird-weather" >&2
  exit 1
fi
if [ -n "$EBIRD_KEY" ] && [ "$MODE" != birdweather ]; then
  echo "--ebird-key only applies with --bird-weather" >&2
  exit 1
fi
if [ "$MODE" = panel ]; then
  if [ -n "$PANEL_ORIENT" ]; then
    case "$PANEL_ORIENT" in
      portrait|landscape) ;;
      *) echo "--orientation must be portrait or landscape" >&2; exit 1 ;;
    esac
  fi
  if [ -n "$PANEL_WINDOW" ]; then
    case "$PANEL_WINDOW" in
      1h|12h|24h|7d|today|all) ;;
      *) echo "--window must be one of: 1h 12h 24h 7d today all" >&2; exit 1 ;;
    esac
  fi
  # --orientation fills in only the dimensions you didn't give (explicit
  # --width/--height always win); the defaults stay landscape 800x480.
  if [ "$PANEL_ORIENT" = portrait ]; then
    [ -n "$PANEL_W" ] || PANEL_W=480
    [ -n "$PANEL_H" ] || PANEL_H=800
  else
    [ -n "$PANEL_W" ] || PANEL_W=800
    [ -n "$PANEL_H" ] || PANEL_H=480
  fi
  for V in "$PANEL_W" "$PANEL_H"; do
    if ! printf '%s' "$V" | LC_ALL=C grep -qE '^[0-9]{1,4}$'; then
      echo "--width/--height must be whole pixels, e.g. 800 480" >&2
      exit 1
    fi
    if [ "$V" -lt 1 ] || [ "$V" -gt 4096 ]; then
      echo "--width/--height must be between 1 and 4096" >&2
      exit 1
    fi
  done
fi

# Validate inputs up front: a bad value would otherwise land in a config file or
# a systemd unit verbatim. These checks also reject a flag passed as a value
# (e.g. "--zip --image-url"), which would fail the format below.
if [ "$MODE" = birdweather ]; then
  if [ -z "$ZIP" ]; then
    echo "--bird-weather needs --zip <ZIP code>, e.g. install.sh --bird-weather --zip 94107" >&2
    exit 1
  fi
  if ! printf '%s' "$ZIP" | LC_ALL=C grep -qE '^[A-Za-z0-9][A-Za-z0-9 -]{1,9}$'; then
    echo "--zip should look like a postal code, e.g. 94107 or SW1A 1AA" >&2
    exit 1
  fi
  if [ -n "$EBIRD_KEY" ] && ! printf '%s' "$EBIRD_KEY" | LC_ALL=C grep -qE '^[A-Za-z0-9]+$'; then
    echo "--ebird-key should be the alphanumeric token from ebird.org/api/keygen" >&2
    exit 1
  fi
fi
if [ "$MODE" = image ]; then
  if [ -z "$IMAGE_URL" ]; then
    echo "--image-url needs a URL, e.g. install.sh --image-url https://bird.example/frame.png" >&2
    exit 1
  fi
  case "$IMAGE_URL" in
    http://*|https://*) ;;
    *) echo "--image-url must start with http:// or https://" >&2; exit 1 ;;
  esac
  if printf '%s' "$IMAGE_URL" | LC_ALL=C grep -q '[^A-Za-z0-9._~:/?#@!$&()*+,;=%-]'; then
    echo "--image-url has characters that are not allowed in a URL" >&2
    exit 1
  fi
fi

# local + birdweather render on the Pi (need a browser); image only fetches.
NEEDS_BROWSER=1
if [ "$MODE" = image ] || [ "$MODE" = panel ]; then NEEDS_BROWSER=0; fi

CONFIG_TXT=/boot/firmware/config.txt
[ -f "$CONFIG_TXT" ] || CONFIG_TXT=/boot/config.txt

echo "1/5  Enabling SPI + I2C (Inky needs both; SPI with no chip-select)..."
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
grep -q "^dtoverlay=spi0-0cs" "$CONFIG_TXT" || echo "dtoverlay=spi0-0cs" | sudo tee -a "$CONFIG_TXT" >/dev/null

echo "2/5  Installing system packages (build tools to compile spidev, libatlas3-base for numpy)..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-dev build-essential libatlas3-base

echo "3/5  Creating venv and installing Python deps..."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-frame.txt
if [ "$NEEDS_BROWSER" = 1 ]; then
  echo "     Installing Playwright + Chromium so the Pi can render the collage (a few minutes)..."
  .venv/bin/pip install -q playwright
  sudo .venv/bin/playwright install-deps chromium
  .venv/bin/playwright install chromium
fi

echo "4/5  Writing config..."
mkdir -p "$HOME/.birdframe"
CONFIG="$HOME/.birdframe/config.toml"
if [ -f "$CONFIG" ]; then
  EXISTING="$(sed -n 's/^# birdframe-mode: //p' "$CONFIG" | head -1)"
  if [ -n "$EXISTING" ] && [ "$EXISTING" != "$MODE" ]; then
    echo "     $CONFIG is set up for '$EXISTING' mode, not '$MODE'." >&2
    echo "     To switch, remove it and re-run:  rm $CONFIG" >&2
    exit 1
  fi
  echo "     $CONFIG already exists, leaving it untouched."
elif [ "$MODE" = local ]; then
  cat > "$CONFIG" <<'CFG'
# birdframe-mode: local
# AvianVisitors frame, local mode: mirrors the BirdNET-Pi on your network.
# This Pi screenshots birdnet.local itself, so there is nothing else to set up.
base_url = "http://birdnet.local"
shoot = true
shoot_title = "Avian Visitors"
shoot_subtitle = "Heard Today"
rotate = 90          # flip to 270 if the frame hangs the other way up
saturation = 0.6
timeout = 45
# If your BirdNET-Pi is behind basic-auth, uncomment and set these:
# basic_user = "..."
# basic_pass = "..."
CFG
elif [ "$MODE" = image ]; then
  BASE="$(printf '%s' "$IMAGE_URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
  # printf, not a heredoc: the URL is written literally, never shell-expanded.
  {
    printf '%s\n' '# birdframe-mode: image'
    printf '%s\n' '# AvianVisitors frame, image mode: fetches a ready-made frame PNG.'
    printf 'base_url = "%s"\n' "$BASE"
    printf 'image_url = "%s"\n' "$IMAGE_URL"
    printf '%s\n' 'shoot = false'
    printf '%s\n' 'rotate = 90          # flip to 270 if the frame hangs the other way up'
    printf '%s\n' 'saturation = 0.6'
  } > "$CONFIG"
elif [ "$MODE" = panel ]; then
  # panel mode: fetch the collage at the panel's native size from the BirdNET-Pi
  # (/avian/api/frame.php) and push to any e-ink display via push_command.
  {
    printf '%s\n' '# birdframe-mode: panel'
    printf '%s\n' '# AvianVisitors panel: fetches the collage at the panel native size from'
    printf '%s\n' '# the BirdNET-Pi and pushes it to any e-ink display (panel.py).'
    printf '%s\n' 'base_url = "http://birdnet.local"   # your BirdNET-Pi'
    printf 'width = %s\n' "$PANEL_W"
    printf 'height = %s\n' "$PANEL_H"
    if [ -n "$PANEL_WINDOW" ]; then
      printf 'window = "%s"  # short-URL time slot (1h 12h 24h 7d today all)\n' "$PANEL_WINDOW"
    else
      printf '%s\n' 'hours = 24'
    fi
    printf '%s\n' '# Inky Impression 7.3" Spectra-6 inks. For mono use [[0,0,0],[255,255,255]];'
    printf '%s\n' '# for a B/W/R panel (e.g. 400x300) use [[255,255,255],[0,0,0],[165,60,56]].'
    printf '%s\n' 'inks = [[236,234,223],[26,26,28],[165,60,56],[198,176,74],[49,71,130],[58,110,72]]'
    printf '%s\n' '# Drive the hardware with your own firmware; {image} is the quantised PNG:'
    printf '%s\n' '# push_command = "sudo ~/my-firmware --image {image}"'
    printf '%s\n' '# heal_hours = 24'
  } > "$CONFIG"
else
  # birdweather: this Pi renders from BirdWeather near $ZIP, gated on the same
  # signature as the other modes - it only redraws when the local top birds change.
  {
    printf '%s\n' '# birdframe-mode: birdweather'
    printf '%s\n' '# AvianVisitors frame, BirdWeather mode: renders the top birds near a ZIP.'
    printf '%s\n' 'species_source = "birdweather"'
    printf 'zip = "%s"\n' "$ZIP"
    printf '%s\n' 'bw_days = 7          # BirdWeather lookback window, in days'
    printf '%s\n' 'bw_country = "us"    # geocoder country for the ZIP'
    printf '%s\n' 'shoot = true         # this Pi renders the collage'
    printf '%s\n' 'shoot_title = "Avian Visitors"'
    printf '%s\n' 'shoot_subtitle = "Heard Today"'
    printf '%s\n' 'rotate = 90          # flip to 270 if the frame hangs the other way up'
    printf '%s\n' 'saturation = 0.6'
  } > "$CONFIG"
fi

echo "5/5  Installing systemd service + timer..."
# Every mode runs the right client against the config on the standard 15-minute
# timer; only the config and the unit differ. display.py renders inline for
# local + birdweather and pushes to the panel only when the birds change.
# panel.py fetches the server-rendered collage and pushes via push_command.
if [ "$MODE" = panel ]; then
  sed "s|/home/monalisa/AvianVisitors/frame|$FRAME|g; s|/home/monalisa|$HOME|g; s|User=monalisa|User=$USER|" \
    systemd/birdpanel.service | sudo tee /etc/systemd/system/birdpanel.service >/dev/null
  sudo cp systemd/birdpanel.timer /etc/systemd/system/birdpanel.timer
  sudo systemctl daemon-reload
  sudo systemctl enable --now birdpanel.timer  # --now starts it immediately, not only on the next boot
else
  sed "s|/home/monalisa/AvianVisitors/frame|$FRAME|g; s|/home/monalisa|$HOME|g; s|User=monalisa|User=$USER|" \
    systemd/birdframe.service | sudo tee /etc/systemd/system/birdframe.service >/dev/null
  # BirdWeather's remote-ZIP eBird fallback reads its key from the unit environment.
  if [ "$MODE" = birdweather ] && [ -n "$EBIRD_KEY" ]; then
    echo "Environment=EBIRD_API_KEY=$EBIRD_KEY" | sudo tee -a /etc/systemd/system/birdframe.service >/dev/null
  fi
  sudo cp systemd/birdframe.timer /etc/systemd/system/birdframe.timer
  sudo systemctl daemon-reload
  sudo systemctl enable --now birdframe.timer  # --now starts it immediately, not only on the next boot
fi

case "$MODE" in
  local)
    cat <<DONE

Installed. The frame mirrors birdnet.local on your network and refreshes every
15 min, only when the birds change. Until the mic has heard its first bird it
shows a plain title card. If the panel hangs upside down, set rotate = 270 in
~/.birdframe/config.toml.
DONE
    ;;
  image)
    cat <<DONE

Installed. The frame fetches its image from
  $IMAGE_URL
and refreshes every 15 min, only when the birds change.
DONE
    ;;
  birdweather)
    cat <<DONE

Installed in BirdWeather mode for ZIP $ZIP. The frame renders the top birds near
you on the Pi and refreshes every 15 min, only when the local top birds change.
DONE
    # The bundled illustrations center on the western U.S. If birds near this ZIP
    # aren't in the cloned set the frame quietly skips them, which has tripped
    # people up - surface it here and point at the generator.
    MISSING="$("$FRAME/.venv/bin/python" "$FRAME/birdweather.py" "$ZIP" --missing 2>/dev/null || true)"
    if [ -n "$MISSING" ]; then
      N="$(printf '%s\n' "$MISSING" | grep -c . || true)"
      NAMES="$(printf '%s\n' "$MISSING" | head -8 | sed 's/.*|/    /')"
      if [ "$N" -gt 8 ]; then NAMES="$NAMES
    ... and $((N - 8)) more"; fi
      cat <<FLAG
Heads up: $N local bird(s) near you aren't in the illustration set you cloned, so
the frame will skip them:
$NAMES
To add them, run this on a laptop or workstation (it needs rembg, which the Pi
can't fit) and commit or copy the new cutouts over:
  python3 $FRAME/generate_illustrations.py --zip $ZIP --gemini-key <KEY>
A paid Google Gemini API key is needed: https://ai.google.dev
FLAG
    fi
    ;;
  panel)
    cat <<DONE

Installed in panel mode for a ${PANEL_W}x${PANEL_H} display. The Pi fetches the
collage from birdnet.local (set base_url in ~/.birdframe/config.toml if it lives
elsewhere) and refreshes every 15 min, only when the birds change. To drive the
panel, uncomment push_command in the config with the path to your firmware; until
then the quantised PNG is dropped in ~/.birdframe/panel.png.
DONE
    ;;
esac

# SPI only takes effect on a reboot, so do it for the user. Skip if SPI is
# already up (e.g. a re-run) so we don't bounce a working frame.
if [ -e /dev/spidev0.0 ]; then
  echo "SPI already active, no reboot needed."
else
  echo "Rebooting to bring SPI up (back on its own in ~1 min)..."
  sleep 4
  sudo reboot
fi
