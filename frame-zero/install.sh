#!/usr/bin/env bash
# Install the AvianVisitors frame-zero display client on a Raspberry Pi Zero
# (Pi OS 32-bit) driving a Pimoroni Inky Impression 7.3" e-ink display wired to
# the GPIO header. Enables SPI + I2C, installs the Inky drivers, and installs a
# systemd service that cycles the /all and /today collages from your BirdNET-Pi,
# each shown for `interval` seconds and re-fetched fresh every cycle.
#
# Run it straight from the repo on a fresh Zero:
#   curl -sSL https://raw.githubusercontent.com/Twarner491/AvianVisitors/avian-visitors/frame-zero/install.sh -o /tmp/frame-zero-install.sh
#   bash /tmp/frame-zero-install.sh
# (or: bash <(curl -sSL <same-url>))
#
# Options:
#   --base-url URL      where the BirdNET-Pi lives (default http://birdnet.local)
#   --interval SECONDS  how long each image stays up (default 300)
#   --source-dir PATH   install from a local copy of frame-zero/ instead of cloning
#                       from GitHub (handy for testing on a box that already has it)
#   --no-reboot         don't reboot at the end even if SPI needs enabling
set -euo pipefail

REPO_URL="https://github.com/Twarner491/AvianVisitors.git"
REPO_DIR="$HOME/avianvisitors-frame"
APP="$REPO_DIR/frame-zero"
BASE_URL="http://birdnet.local"
INTERVAL=300
SOURCE_DIR=""
REBOOT_IF_NEEDED=1
RUN_AS="${SUDO_USER:-$USER}"

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this script as a normal user (it sudoes when it needs to), not as root." >&2
  exit 1
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage ;;
    --base-url)
      [ $# -ge 2 ] || { echo "--base-url needs a value, e.g. http://birdnet.local" >&2; exit 1; }
      BASE_URL="$2"; shift 2 ;;
    --base-url=*) BASE_URL="${1#*=}"; shift ;;
    --interval)
      [ $# -ge 2 ] || { echo "--interval needs a value in seconds, e.g. 300" >&2; exit 1; }
      INTERVAL="$2"; shift 2 ;;
    --interval=*) INTERVAL="${1#*=}"; shift ;;
    --source-dir)
      [ $# -ge 2 ] || { echo "--source-dir needs a path to a local copy of frame-zero/" >&2; exit 1; }
      SOURCE_DIR="${2%/}"; shift 2 ;;
    --source-dir=*) SOURCE_DIR="${1#*=}"; shift ;;
    --no-reboot) REBOOT_IF_NEEDED=0; shift ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 1 ;;
  esac
done

case "$BASE_URL" in
  http://*|https://*) ;;
  *) echo "--base-url must start with http:// or https://, e.g. http://birdnet.local" >&2; exit 1 ;;
esac
case "$BASE_URL" in
  *' '*) echo "--base-url must not contain spaces" >&2; exit 1 ;;
esac
if ! printf '%s' "$INTERVAL" | LC_ALL=C grep -qE '^[0-9]+$' || [ "$INTERVAL" -lt 30 ]; then
  echo "--interval must be a whole number of seconds, at least 30 (the panel needs time to refresh)" >&2
  exit 1
fi

echo "1/5  Fetching the frame-zero files from the repo..."
if [ -n "$SOURCE_DIR" ]; then
  APP="$SOURCE_DIR"
  [ -f "$APP/install.sh" ] || { echo "--source-dir does not look like a frame-zero/ folder (no install.sh inside)" >&2; exit 1; }
elif [ ! -d "$REPO_DIR/.git" ]; then
  GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --filter=blob:none --sparse "$REPO_URL" "$REPO_DIR"
  git -C "$REPO_DIR" sparse-checkout set frame-zero
else
  git -C "$REPO_DIR" pull --quiet --ff-only || echo "  (repo update failed; continuing with the files already present)"
fi

echo "2/5  Enabling SPI + I2C (SPI for the panel, I2C to read its EEPROM)..."
CONFIG_TXT=/boot/firmware/config.txt
[ -f "$CONFIG_TXT" ] || CONFIG_TXT=/boot/config.txt
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
for OVERLAY in "dtoverlay=i2c1" "dtoverlay=spi0-0cs"; do
  if ! grep -q "^$OVERLAY" "$CONFIG_TXT"; then
    echo "$OVERLAY" | sudo tee -a "$CONFIG_TXT" >/dev/null
  fi
done

echo "3/5  Installing system packages and the Inky drivers..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip python3-spidev \
  python3-pil python3-numpy
python3 -m venv --system-site-packages "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
# --no-deps: numpy/Pillow/spidev/gpiod come from apt (fast, ARMv6-safe); only the
# pure-Python parts are pip-installed.
"$APP/.venv/bin/pip" install -q --no-deps gpiodevice smbus2 inky

echo "4/5  Writing the config..."
CONFIG="$APP/config.toml"
if [ -f "$CONFIG" ]; then
  echo "     $CONFIG already exists, leaving it untouched."
else
  {
    printf '# Written by install.sh; edit here and run: sudo systemctl restart birdframe-zero\n'
    printf 'base_url = "%s"\n' "$BASE_URL"
    printf 'windows = ["all", "today"]\n'
    printf 'interval = %s\n' "$INTERVAL"
    printf 'saturation = 0.5\n'
    printf '# Most 7.3" boards auto-detect over I2C. Pre-EEPROM boards: uncomment\n'
    printf '# cs_pin = 8\n'
    printf '# dc_pin = 24\n'
    printf '# reset_pin = 25\n'
    printf '# busy_pin = 17\n'
  } > "$CONFIG"
fi

echo "5/5  Installing the systemd service..."
if ! id -nG "$RUN_AS" | tr ' ' '\n' | grep -qx spi; then
  sudo usermod -aG gpio,spi "$RUN_AS" || true
fi
sed "s|__APP__|$APP|g; s|__USER__|$RUN_AS|g" \
  "$APP/systemd/birdframe-zero.service" \
  | sudo tee /etc/systemd/system/birdframe-zero.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now birdframe-zero.service

cat <<DONE

Installed. The frame now cycles
  $BASE_URL/all   and   $BASE_URL/today
on the Inky Impression 7.3, each for $INTERVAL s, re-fetching the images every
cycle so they track the day. The panel will do its first (slow, ~40 s) refresh
now; watch it with:
  journalctl -u birdframe-zero -f

Change behaviour in $CONFIG, then:
  sudo systemctl restart birdframe-zero
DONE

# The Inky driver needs SPI0 present (spidev0.0) but with no hardware chip
# select claimed (spi0-0cs frees GPIO8 for software CS). Both changes only take
# effect on a reboot. Detect "set up correctly" as: spidev0.0 exists AND the
# spidev1/CS1 node is gone (a live raspi-config apply can create spidev0.0
# without the overlay having actually taken effect at boot).
if [ -e /dev/spidev0.0 ] && [ ! -e /dev/spidev0.1 ]; then
  echo "SPI is set up correctly (spi0-0cs active), no reboot needed."
else
  if [ "$REBOOT_IF_NEEDED" = 1 ]; then
    echo "Rebooting to bring SPI + I2C up (the frame starts on its own in ~1 min)..."
    sleep 4
    sudo reboot
  else
    echo "SPI is not set up yet; reboot when you're ready."
  fi
fi
