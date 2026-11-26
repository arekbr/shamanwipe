#!/usr/bin/env bash
# Runs INSIDE the container debian:trixie (amd64). Input: /src (repo, read-only), output: /out.
# Artifacts reach /out only after all checks have passed.
set -euo pipefail
: "${SW_VERSION:?SW_VERSION missing}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends live-build ca-certificates python3 xorriso >/dev/null

# Rosetta + Docker: debootstrap must not conclude that it runs in Docker (it would create a /proc -> /proc symlink) - see the overlay scripts
rm -f /.dockerenv
if grep -qs '[[:space:]]/docker/.*/sys/fs/cgroup' /proc/1/mountinfo; then
  echo "ERROR: debootstrap will still detect Docker via /proc/1/mountinfo" >&2; exit 7
fi
install -m 0755 /src/scripts/debootstrap-rosetta /usr/local/sbin/debootstrap
install -m 0755 /src/scripts/chroot-rosetta /usr/local/sbin/chroot

B=/build
rm -rf "$B"; mkdir -p "$B"
cp -a /src/lb/. "$B"/
install -D -m 0755 /src/src/shamanwipe "$B/config/includes.chroot/usr/local/sbin/shamanwipe"
install -D -m 0644 /src/assets/logo.png "$B/config/includes.chroot/usr/share/shamanwipe/logo.png"  # PDF report header
printf '%s\n' "$SW_VERSION" > "$B/config/includes.chroot/etc/shamanwipe-version"

mkdir -p /cache/lb
# A bootstrap cache written while /proc or /sys was mounted is poisoned (an interrupted write can leave
# chroot/sys/kernel behind and make the next build fail in installer_chroot). Remove such a cache before building.
if [ -d /cache/lb/bootstrap ] && { [ -n "$(ls -A /cache/lb/bootstrap/sys 2>/dev/null)" ] || [ -n "$(ls -A /cache/lb/bootstrap/proc 2>/dev/null)" ] || [ ! -e /cache/lb/bootstrap/etc/os-release ]; }; then
  echo "WARNING: poisoned/incomplete bootstrap cache - removing" >&2
  rm -rf /cache/lb/bootstrap
fi
ln -sfn /cache/lb "$B/cache"

cd "$B"
lb config
RC=0
lb build > /out/build.log 2>&1 || RC=$?
grep -aE '^(P:|E:)' /out/build.log | tail -25 || true
if [ "$RC" -ne 0 ]; then echo "ERROR: lb build rc=$RC" >&2; exit "$RC"; fi

ISO_SRC="$(ls -1 "$B"/*.hybrid.iso 2>/dev/null | head -1 || true)"
[ -n "$ISO_SRC" ] || { echo "ERROR: lb build rc=0 but no ISO" >&2; exit 1; }
PKG_SRC="$(ls -1 "$B"/*.packages | head -1)"

/src/scripts/check-packages.sh "$PKG_SRC"

# Boot files in the finished image (shim + signed GRUB for Secure Boot, isolinux for BIOS)
FILE_LIST="$(xorriso -indev "$ISO_SRC" -find / -type f 2>/dev/null)"
for f in /EFI/boot/bootx64.efi /EFI/boot/grubx64.efi /isolinux/isolinux.bin /live/vmlinuz /live/initrd.img /live/filesystem.squashfs; do
  echo "$FILE_LIST" | grep -qi "^'\?${f}'\?$" || { echo "ERROR: $f missing in the ISO" >&2; exit 8; }
done

NAME="shamanwipe-${SW_VERSION}-amd64"
cp "$ISO_SRC" "/out/${NAME}.iso"
cp "$PKG_SRC" "/out/${NAME}.packages"
( cd /out && sha256sum "${NAME}.iso" > "${NAME}.iso.sha256" )
echo "OK: ${NAME}.iso"
