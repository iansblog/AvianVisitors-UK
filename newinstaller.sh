#!/usr/bin/env bash
# AvianVisitors-UK Installer
# Based on BirdNET-Pi by Patrick McGuire (Nachtzuster)
# UK illustration pipeline and collage by Twarner491
#
# Installs a BirdNET-Pi acoustic bird monitor with a live kachō-e bird
# collage optimised for UK species.  Run as a non-root user with
# passwordless sudo:
#
#   curl -s https://raw.githubusercontent.com/Twarner491/AvianVisitors-UK/main/newinstaller.sh | bash

set -e

if [ "$EUID" == 0 ]; then
  echo "Please run as a non-root user."
  exit 1
fi

if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "x86_64" ]; then
  echo "AvianVisitors-UK requires a 64-bit OS."
  echo "Detected: $(uname -m)"
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

# Clone into the standard BirdNET-Pi directory (upstream scripts hardcode this path)
INSTALL_DIR="${HOME}/BirdNET-Pi"
REPO_URL="https://github.com/Twarner491/AvianVisitors-UK.git"
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
