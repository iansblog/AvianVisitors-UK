#!/usr/bin/env bash
# AvianVisitors-UK Installer
# Based on BirdNET-Pi by Patrick McGuire (Nachtzuster)
# UK illustration pipeline and collage by Twarner491
#
# Installs a BirdNET-Pi acoustic bird monitor with a live kachō-e bird
# collage optimised for UK species.  Run as a non-root user with
# passwordless sudo:
#
#   curl -s https://raw.githubusercontent.com/iansblog/AvianVisitors-UK/main/newinstaller.sh | bash
#
# Hardware coverage:
#   - Raspberry Pi 3, 4 and 5 (64-bit OS required)
#   - x86_64 (VM / desktop) installs are supported too
#   - < 2 GB RAM: enables zram + swap and disables on-demand AI
#     illustration generation to keep the system stable on a Pi 3.

set -e

if [ "$EUID" == 0 ]; then
  echo "Please run as a non-root user."
  exit 1
fi

# ------------------------------- Hardware detection --------------------------
ARCH=$(uname -m)
PI_MODEL="unknown"
[ -r /proc/device-tree/model ] && PI_MODEL=$(tr -d '\0' < /proc/device-tree/model)
TOTAL_RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
TOTAL_RAM_MB=${TOTAL_RAM_MB:-0}

echo ""
echo "=== AvianVisitors-UK hardware report ==="
echo "  Model : ${PI_MODEL}"
echo "  Arch  : ${ARCH}"
echo "  RAM   : ${TOTAL_RAM_MB} MB"
echo "========================================"
echo ""

# 32-bit boards cannot run the tflite wheel. Give actionable guidance for
# armv7l (Pi 2/3 running 32-bit OS) instead of a generic failure message.
if [ "$ARCH" == "armv7l" ] || [ "$ARCH" == "armv6l" ]; then
  echo "You are running a 32-bit operating system ($ARCH)."
  echo "AvianVisitors-UK requires a 64-bit OS - the tflite runtime has no"
  echo "32-bit ARM build for Python 3.10+."
  echo ""
  echo "Raspberry Pi 3, 4 and 5 all support 64-bit. Reinstall with the"
  echo "64-bit Raspberry Pi OS image (Raspberry Pi Imager -> Operating System"
  echo "-> Raspberry Pi OS (64-bit)) and re-run this installer."
  exit 1
fi

if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "x86_64" ]; then
  echo "Unsupported architecture: $ARCH"
  echo "AvianVisitors-UK supports aarch64 (Raspberry Pi 3/4/5) and x86_64."
  exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')" 2>/dev/null || echo "00")
if [ "${PY_VERSION}" == "39" ]; then
  echo "### AvianVisitors-UK requires Python 3.10+. Bullseye is deprecated, please use Bookworm or later. ###"
  [ -z "${FORCE_BULLSEYE}" ] && exit 1
fi

# We require passwordless sudo
sudo -K
if ! sudo -n true; then
  echo "Passwordless sudo is not working. Aborting."
  exit 1
fi

HOME=$HOME
USER=$USER
export HOME=$HOME
export USER=$USER

# Ensure git and jq are available
PACKAGES_MISSING=
for cmd in git jq; do
  if ! which "$cmd" &>/dev/null; then
    PACKAGES_MISSING="${PACKAGES_MISSING} $cmd"
  fi
done
if [ -n "$PACKAGES_MISSING" ]; then
  sudo apt-get update
  sudo apt-get -y install $PACKAGES_MISSING
fi

# < 2 GB RAM (Pi 3 / Zero 2W): enable zram + swap so the analysis service
# has headroom. AI illustration generation is cloud-based and works on all
# boards - rembg (the only local part) auto-skips when RAM is low.
export LOW_RAM=0
if [ "$TOTAL_RAM_MB" -lt 2048 ]; then
  export LOW_RAM=1
  echo "Detected ${TOTAL_RAM_MB} MB RAM."
  echo "Enabling zram + swap. AI illustration generation stays enabled -"
  echo "rembg will skip automatically if memory gets tight."
  echo ""
fi

# Clone into the standard BirdNET-Pi directory (upstream scripts hardcode this path)
INSTALL_DIR="${HOME}/BirdNET-Pi"
REPO_URL="https://github.com/iansblog/AvianVisitors-UK.git"
BRANCH="main"

if [ -d "$INSTALL_DIR" ]; then
  echo "Directory $INSTALL_DIR already exists."
  echo "If this is a fresh install, remove it first: rm -rf $INSTALL_DIR"
  exit 1
fi

echo "Cloning AvianVisitors-UK..."
git clone -b "$BRANCH" --depth=1 "$REPO_URL" "$INSTALL_DIR" || {
  echo "Clone failed. Check your network connection and try again."
  exit 1
}

# Run the BirdNET-Pi installer (handles system deps, services, venv, etc.)
"$INSTALL_DIR/scripts/install_birdnet.sh"
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  # Low-RAM tuning after the core install so swap/zram exist before the
  # analysis service starts churning.
  if [ "$LOW_RAM" == "1" ]; then
    echo "Applying low-RAM tuning (zram + swap)..."
    "$INSTALL_DIR/scripts/install_zram_service.sh" || echo "zram setup failed (non-fatal)"
    if command -v dphys-swapfile >/dev/null 2>&1; then
      sudo sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile || true
      sudo dphys-swapfile setup && sudo dphys-swapfile swapon || echo "swap resize failed (non-fatal)"
    fi
  fi

  # Set up the illustration venv (rembg + Pillow) on every board - the AI
  # generation is cloud-side, rembg only runs locally when RAM allows.
  # The system python is PEP 668 managed on Bookworm+, so a venv is required.
  if [ -f "$INSTALL_DIR/avian/scripts/requirements.txt" ]; then
    echo "Setting up illustration venv (rembg + onnxruntime)..."
    if [ ! -d "$INSTALL_DIR/avian/scripts/.venv" ]; then
      python3 -m venv "$INSTALL_DIR/avian/scripts/.venv"
    fi
    "$INSTALL_DIR/avian/scripts/.venv/bin/pip" install --upgrade pip >/dev/null 2>&1 || true
    "$INSTALL_DIR/avian/scripts/.venv/bin/pip" install -r "$INSTALL_DIR/avian/scripts/requirements.txt" || echo "illustration deps failed (non-fatal)"
  fi

  echo ""
  echo "============================================"
  echo "  AvianVisitors-UK installed successfully!"
  echo "  Collage: http://$(hostname).local/"
  echo "  Admin:   http://$(hostname).local/index.php"
  echo "============================================"
  echo ""
  sudo reboot
else
  echo "The installation exited unsuccessfully."
  exit 1
fi
