#!/usr/bin/env bash
# Runs INSIDE the (amd64) container via scripts/make-usb.sh image. Input: /iso (ISO, read-only), output: /outdir.
# Builds the USB stick image: a copy of the ISO + MBR partition 3 (FAT32, label SW-REPORTS) after the ISO image, on a 1 MiB boundary.
# The ISO is a hybrid MBR+GPT+APM image without a protective 0xEE partition (sfdisk reports "label: dos"; xorriso uses
# "MBR isohybrid cyl-align-on GPT APM"), so the kernel and UEFI read the MBR and an MBR entry is enough; the GPT is
# left untouched (it covers the ISO area only).
# Ed25519 key: generated in the container's tmpfs, encrypted with the operator's passphrase (openssl asks on the
# terminal; without a terminal the passphrase is read from stdin - tests only), the plain copy is destroyed.
# Public key: /outdir/key-<fingerprint16>.pub.pem.
set -euo pipefail
: "${SW_VERSION:?}" "${REPORTS_MIB:?}" "${SW_KEY:?}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq --no-install-recommends fdisk dosfstools openssl util-linux >/dev/null

ISO="/iso/shamanwipe-${SW_VERSION}-amd64.iso"
IMG="/outdir/shamanwipe-${SW_VERSION}-pendrive.img"
( cd /iso && sha256sum -c "$(basename "$ISO").sha256" )
ISO_B=$(stat -c %s "$ISO")
START=$(( (ISO_B + 1048575) / 1048576 * 2048 ))          # 512 B sectors, 1 MiB boundary
cp "$ISO" "$IMG.tmp"
truncate -s $(( START * 512 + REPORTS_MIB * 1048576 )) "$IMG.tmp"
sfdisk -d "$IMG.tmp" | grep -E '^/' > /tmp/before
echo "start=${START}, type=c" | sfdisk --append --no-reread --no-tell-kernel "$IMG.tmp" >/dev/null
sfdisk -d "$IMG.tmp" | grep -E '^/' > /tmp/after
# Check: ISO partitions unchanged, exactly one new partition, type c, located after the ISO
head -2 /tmp/after | cmp -s - /tmp/before || { echo "ERROR: ISO partitions changed" >&2; exit 3; }
[ "$(wc -l < /tmp/after)" -eq 3 ] && grep -qE "3 : start= *${START}, .*type=c" /tmp/after || { echo "ERROR: partition 3 mismatch" >&2; cat /tmp/after >&2; exit 3; }

# macOS reads APM first (from the ISO hybrid), then GPT - both describe only the ISO area, so SW-REPORTS would be
# INVISIBLE on a Mac (diskutil reports "Apple_partition_scheme"). We invalidate the signatures of the APM entries ("PM")
# and of both GPT headers ("EFI PART"); bytes 0-1 "ER" stay (they are also the start of the MBR boot code). After that
# macOS and Windows read the MBR and see the FAT32 SW-REPORTS; BIOS boot (ISOLINUX) and UEFI boot (type 0xEF partition
# in the MBR) are unaffected (checked in QEMU with the image attached as a USB disk).
read_bytes() { dd if="$IMG.tmp" bs=1 skip="$1" count="$2" 2>/dev/null | tr -d '\0'; }
zero_bytes() { dd if=/dev/zero of="$IMG.tmp" bs=1 seek="$1" count="$2" conv=notrunc 2>/dev/null; }
if [ "$(read_bytes 0 2)" = ER ] && [ "$(read_bytes 2048 2)" = PM ]; then
  N_APM=$(od -An -tu4 --endian=big -j 2052 -N4 "$IMG.tmp" | tr -d ' ')
  for b in $(seq 1 "$N_APM"); do
    [ "$(read_bytes $((b * 2048)) 2)" = PM ] || { echo "ERROR: APM entry $b has no PM signature" >&2; exit 6; }
    zero_bytes $((b * 2048)) 2
  done
fi
if [ "$(read_bytes 512 8)" = "EFI PART" ]; then
  ALT=$(od -An -tu8 --endian=little -j 544 -N8 "$IMG.tmp" | tr -d ' ')
  [ "$(read_bytes $((ALT * 512)) 8)" = "EFI PART" ] || { echo "ERROR: GPT backup not where the header points (LBA $ALT)" >&2; exit 6; }
  zero_bytes 512 8; zero_bytes $((ALT * 512)) 8
fi
[ "$(read_bytes 2048 2)" != PM ] && [ "$(read_bytes 512 8)" != "EFI PART" ] && [ "$(read_bytes 0 2)" = ER ] || { echo "ERROR: APM/GPT still valid" >&2; exit 6; }
sfdisk -d "$IMG.tmp" | grep -E '^/' | cmp -s - /tmp/after || { echo "ERROR: MBR changed while invalidating APM/GPT" >&2; exit 6; }

LOOP=$(losetup -f --show -o $(( START * 512 )) --sizelimit $(( REPORTS_MIB * 1048576 )) "$IMG.tmp")
M=/mnt/sw-reports
cleanup() { mountpoint -q "$M" && umount "$M"; losetup -d "$LOOP" 2>/dev/null || true; rm -f /dev/shm/sw-key.pem; }
trap cleanup EXIT
mkfs.vfat -F 32 -n SW-REPORTS "$LOOP" >/dev/null
mkdir -p "$M" && mount "$LOOP" "$M"
mkdir -p "$M/reports" "$M/key"
cat > "$M/operator.conf" <<'EOF'
# Operator details for reports (NIST SP 800-88r2 section 4.6). The program reads them on every erase;
# in manual mode they can be edited before erasing. Format: key=value.
name=
title=
organization=
location=
contact=
EOF
FPR=none
if [ "$SW_KEY" = yes ]; then
  ( umask 077; openssl genpkey -algorithm ed25519 -out /dev/shm/sw-key.pem )
  openssl pkey -in /dev/shm/sw-key.pem -pubout -out "$M/key/shamanwipe-signing.pub.pem"
  if [ -t 0 ]; then
    echo ">> Report signing key passphrase (twice). Store it in your password manager - without it the reports will be unsigned."
    openssl pkey -in /dev/shm/sw-key.pem -aes-256-cbc -out "$M/key/shamanwipe-signing.pem"
  else
    openssl pkey -in /dev/shm/sw-key.pem -aes-256-cbc -passout stdin -out "$M/key/shamanwipe-signing.pem"
  fi
  rm -f /dev/shm/sw-key.pem
  # Check: the private key must NOT open without a passphrase (it is encrypted)
  if openssl pkey -in "$M/key/shamanwipe-signing.pem" -passin pass: -noout 2>/dev/null; then
    echo "ERROR: the private key is not encrypted" >&2; exit 4
  fi
  FPR=$(openssl pkey -pubin -in "$M/key/shamanwipe-signing.pub.pem" -outform DER | sha256sum | cut -c1-16)
  cp "$M/key/shamanwipe-signing.pub.pem" "/outdir/key-${FPR}.pub.pem"
fi
printf 'ShamanWipe USB %s, created %s, key fingerprint %s\n' "$SW_VERSION" "$(date -u +%FT%TZ)" "$FPR" > "$M/SHAMANWIPE.txt"
# Checksums of the SW-REPORTS files for verification after writing (the whole device cannot be compared: the OS adds its own files)
( cd "$M" && find key operator.conf SHAMANWIPE.txt -type f | sort | xargs sha256sum ) > "/outdir/$(basename "$IMG").sw-reports.sha256"
sync; umount "$M"
fsck.vfat -n "$LOOP" >/dev/null || { echo "ERROR: fsck.vfat SW-REPORTS" >&2; exit 5; }
losetup -d "$LOOP"; trap - EXIT
mv "$IMG.tmp" "$IMG"
( cd /outdir && sha256sum "$(basename "$IMG")" > "$(basename "$IMG").sha256" )
echo "OK: $(basename "$IMG") ($(( $(stat -c %s "$IMG") / 1048576 )) MiB), SW-REPORTS ${REPORTS_MIB} MiB from sector ${START}, key fingerprint ${FPR}"
