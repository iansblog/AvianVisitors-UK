#!/usr/bin/env bash
# Configure a compressed in-RAM swap device (zram) sized to the board's RAM.
# On low-RAM boards (Pi 3, Zero 2W) zram relieves memory pressure for the
# BirdNET analysis service; it also speeds up swapping compared to disk.

TOTAL_RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
TOTAL_RAM_MB=${TOTAL_RAM_MB:-0}

# Size zram to ~50% of RAM, capped between 256 MB and 1 GB. zstd compresses
# typically 3-4x, so 512 MB zram on a 1 GB board gives ~1.5-2 GB effective.
ZRAM_MB=512
if [ "$TOTAL_RAM_MB" -gt 0 ]; then
  ZRAM_MB=$(( TOTAL_RAM_MB / 2 ))
  [ "$ZRAM_MB" -lt 256 ] && ZRAM_MB=256
  [ "$ZRAM_MB" -gt 1024 ] && ZRAM_MB=1024
fi

echo "Configuring zram.service (${ZRAM_MB}M on ${TOTAL_RAM_MB} MB RAM)"
sudo touch /etc/modules-load.d/zram.conf
echo 'zram' | sudo tee /etc/modules-load.d/zram.conf
sudo touch /etc/modprobe.d/zram.conf
echo 'options zram num_devices=1' | sudo tee /etc/modprobe.d/zram.conf
sudo touch /etc/udev/rules.d/99-zram.rules
echo "KERNEL==\"zram0\", ATTR{comp_algorithm}=\"zstd\", ATTR{disksize}=\"${ZRAM_MB}M\", TAG+=\"systemd\"" \
  | sudo tee /etc/udev/rules.d/99-zram.rules
sudo touch /etc/systemd/system/zram.service
echo "Installing zram.service"
cat << EOF | sudo tee /etc/systemd/system/zram.service
[Unit]
Description=Swap with zram
After=multi-user.target
[Service]
Type=oneshot 
RemainAfterExit=true
ExecStartPre=/sbin/mkswap /dev/zram0
ExecStart=/sbin/swapon -p 15 /dev/zram0
ExecStop=/sbin/swapoff /dev/zram0
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable zram
echo "You'll need to reboot for this to take effect."
