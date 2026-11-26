#!/usr/bin/env bash
# ShamanWipe USB stick: image = ISO + SW-REPORTS partition (FAT32) holding the report signing key and operator.conf.
#
#   scripts/make-usb.sh image [--reports-mib N] [--no-key] [--out-dir DIR]
#       -> out/shamanwipe-<version>-pendrive.img (+ .sha256), public key copied to keys/<fingerprint16>.pub.pem
#       Built in a container (Colima profile "shamanwipe"). The operator types the key passphrase; store it in your
#       password manager. There is ONE KEY PER STICK; keys/ in the repo is the list of keys trusted when verifying reports.
#
#   scripts/make-usb.sh write <device> [--dry-run] [--image <.img file>]
#       macOS: /dev/diskN (whole disk), Linux: /dev/sdX. USB media only (refuses internal disks), shows model and size,
#       requires typing "WRITE <name>", then verifies by reading back: MBR + ISO byte for byte, SW-REPORTS files against
#       the checksums recorded at build time (not the whole device - the OS mounts SW-REPORTS and adds its own files).
#       --dry-run: all checks, nothing is written.
#
#   scripts/make-usb.sh verify <device> [--image <.img file>]   - the same verification without writing
#
# Modifies: out/ (image), keys/ (public key), and in the "write" step ONLY the named and confirmed device.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(cat VERSION)"
IMG="out/shamanwipe-${VERSION}-pendrive.img"
CTX=colima-shamanwipe

refuse() { echo "REFUSED: $*" >&2; exit 3; }

image() {
  local mib=1024 key=yes out_dir=out
  while [ $# -gt 0 ]; do
    case "$1" in
      --reports-mib) mib="$2"; shift 2 ;;
      --no-key) key=no; shift ;;
      --out-dir) out_dir="$2"; shift 2 ;;   # tests: image and public key go to another directory (keys/ untouched)
      *) refuse "unknown option $1" ;;
    esac
  done
  [[ "$mib" =~ ^[0-9]+$ ]] && [ "$mib" -ge 64 ] || refuse "--reports-mib >= 64"
  [ -s "out/shamanwipe-${VERSION}-amd64.iso" ] || refuse "ISO missing - run ./build.sh first"
  if ! colima status shamanwipe >/dev/null 2>&1; then
    local docker_ctx; docker_ctx="$(docker context show 2>/dev/null || true)"
    echo ">> starting Colima profile shamanwipe - stop it after use: colima stop shamanwipe"
    # --activate=false: do not change the user's default Docker context (same as build.sh)
    colima start shamanwipe --activate=false --vm-type vz --vz-rosetta --cpu 8 --memory 12 --disk 60 >/dev/null
    [ "$(docker context show 2>/dev/null || true)" = "$docker_ctx" ] || refuse "the default Docker context changed"
  fi
  mkdir -p "$out_dir"; out_dir="$(cd "$out_dir" && pwd)"
  case "$out_dir" in "$HOME"/*) ;; *) refuse "--out-dir must be inside \$HOME (Colima mounts only \$HOME)" ;; esac
  local tty=()
  [ -t 0 ] && tty=(-t)
  rm -f "$out_dir"/key-*.pub.pem
  docker --context "$CTX" run --rm -i "${tty[@]}" --privileged --platform linux/amd64 \
    -v "$PWD/scripts":/scripts:ro -v "$PWD/out":/iso:ro -v "$out_dir":/outdir \
    -e SW_VERSION="$VERSION" -e REPORTS_MIB="$mib" -e SW_KEY="$key" \
    debian:13 /scripts/make-usb-in-container.sh
  if [ "$out_dir" = "$PWD/out" ]; then
    mkdir -p keys
    for p in out/key-*.pub.pem; do
      [ -e "$p" ] || continue
      mv "$p" "keys/${p#out/key-}"
      echo ">> public key: keys/${p#out/key-} (add it to the repo)"
    done
  fi
  ( cd "$out_dir" && shasum -a 256 -c "$(basename "$IMG").sha256" )
}

file_size() { stat -f %z "$1" 2>/dev/null || stat -c %s "$1"; }

write() {
  local dev="" dry_run=no
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry_run=yes; shift ;;
      --image) IMG="$2"; shift 2 ;;   # default: out/shamanwipe-<version>-pendrive.img
      -*) refuse "unknown option $1" ;;
      *) dev="$1"; shift ;;
    esac
  done
  [ -n "$dev" ] || refuse "specify a device (macOS: /dev/diskN, Linux: /dev/sdX)"
  [ -s "$IMG" ] || refuse "$IMG missing - run first: $0 image"
  ( cd "$(dirname "$IMG")" && shasum -a 256 -c "$(basename "$IMG").sha256" ) >/dev/null || refuse "image checksum mismatch"
  local img_size; img_size=$(file_size "$IMG")
  local name size desc raw
  case "$(uname)" in
    Darwin)
      [[ "$dev" =~ ^/dev/disk[0-9]+$ ]] || refuse "specify the whole disk as /dev/diskN (not a partition)"
      local info; info="$(diskutil info -plist "$dev")" || refuse "diskutil does not know $dev"
      field() { plutil -extract "$1" raw -o - - <<<"$info" 2>/dev/null || echo "?"; }
      [ "$(field WholeDisk)" = true ] || refuse "$dev is not a whole disk"
      [ "$(field Internal)" = false ] || refuse "$dev is an INTERNAL disk"
      local proto; proto="$(field BusProtocol)"
      if [ "$proto" != USB ]; then
        # A disk image (hdiutil) is allowed ONLY as a test hook
        [ "$proto" = "Disk Image" ] && [ "${SW_TEST_DISK_IMAGE:-}" = 1 ] || refuse "$dev is not USB (protocol: $proto)"
      fi
      size="$(field TotalSize)"; desc="$(field MediaName) $(field IORegistryEntryName)"
      name="${dev#/dev/}"; raw="/dev/r${name}"
      ;;
    Linux)
      [[ "$dev" =~ ^/dev/sd[a-z]+$ ]] || refuse "specify the whole disk as /dev/sdX"
      [ "$(lsblk -dno TRAN "$dev")" = usb ] || refuse "$dev is not USB ($(lsblk -dno TRAN "$dev"))"
      ! lsblk -no MOUNTPOINTS "$dev" | grep -qE '^/(boot|home)?$' || refuse "$dev has a mounted system"
      size="$(lsblk -bdno SIZE "$dev")"; desc="$(lsblk -dno VENDOR,MODEL,SERIAL "$dev")"
      name="${dev#/dev/}"; raw="$dev"
      ;;
    *) refuse "unsupported system $(uname)" ;;
  esac
  [[ "$size" =~ ^[0-9]+$ ]] && [ "$size" -ge "$img_size" ] || refuse "device too small: $size B < image $img_size B"
  echo "Device: $dev - $desc - $(( size / 1000000 )) MB"
  echo "Image:  $IMG - $(( img_size / 1048576 )) MiB"
  echo "ALL data on $dev will be destroyed."
  [ "$dry_run" = yes ] && { echo "DRY RUN: checks passed, nothing was written."; return 0; }
  local confirm; read -r -p "Type: WRITE ${name}  > " confirm
  [ "$confirm" = "WRITE ${name}" ] || refuse "not confirmed - nothing was written"
  local sudo=(); [ -w "$raw" ] || sudo=(sudo)
  if [ "$(uname)" = Darwin ]; then
    diskutil unmountDisk "$dev" >/dev/null
    "${sudo[@]}" dd if="$IMG" of="$raw" bs=4m
  else
    "${sudo[@]}" dd if="$IMG" of="$raw" bs=4M oflag=direct conv=fsync status=progress
  fi
  sync
  verify_media "$dev" "$raw" "${sudo[@]}" || exit 6
  echo "OK: written and verified by reading back."
  [ "$(uname)" = Darwin ] && diskutil eject "$dev" >/dev/null && echo "Device ejected."
  return 0
}

# Proof of the write = reading the device back, not the exit code of dd. NOT a checksum of the whole device: the OS
# mounts SW-REPORTS right after dd and writes to it (macOS creates .fseventsd and .Spotlight-V100), so a whole-device
# checksum differs from the image even after a correct write. We check: (1) byte for byte, the area from sector 0 to
# the start of SW-REPORTS = MBR + ISO (this is what the computer boots from); (2) the SW-REPORTS files against the
# checksums recorded when the image was built.
verify_media() {  # <device> <raw device> [sudo]
  local dev="$1" raw="$2"; shift 2
  local sudo=("$@") lba nbytes h_img h_dev
  lba=$(od -An -tu4 -j $((446 + 2 * 16 + 8)) -N4 "$IMG" | tr -d ' ')
  nbytes=$((lba * 512))
  [ "$nbytes" -gt 0 ] || { echo "ERROR: the image has no partition 3 (SW-REPORTS)" >&2; return 6; }
  h_img=$(head -c "$nbytes" "$IMG" | shasum -a 256 | cut -d' ' -f1)
  h_dev=$("${sudo[@]}" head -c "$nbytes" "$raw" | shasum -a 256 | cut -d' ' -f1)
  [ "$h_dev" = "$h_img" ] || { echo "ERROR: boot area (MBR + ISO, $nbytes B) on the device != image ($h_dev != $h_img)" >&2; return 6; }
  echo "OK: boot area (MBR + ISO, $((nbytes / 1048576)) MiB) matches byte for byte (SHA-256 $h_img)."
  local list="$IMG.sw-reports.sha256"
  [ -s "$list" ] || { echo "WARNING: $list missing - SW-REPORTS files not checked (image built by an older version)" >&2; return 0; }
  list="$(cd "$(dirname "$list")" && pwd)/$(basename "$list")"
  local mp="" tmp="" rc=0 i
  if [ "$(uname)" = Darwin ]; then
    for i in 1 2 3 4 5 6 7 8 9 10; do  # automount may take a moment after dd
      mp=$(diskutil info -plist "${dev}s3" 2>/dev/null | plutil -extract MountPoint raw -o - - 2>/dev/null || true)
      [ -n "$mp" ] && break
      diskutil mount readOnly "${dev}s3" >/dev/null 2>&1 || sleep 1
    done
  else
    tmp=$(mktemp -d); "${sudo[@]}" mount -o ro "${dev}3" "$tmp" && mp="$tmp"
  fi
  [ -n "$mp" ] || { echo "ERROR: cannot mount SW-REPORTS from $dev" >&2; return 6; }
  ( cd "$mp" && shasum -a 256 -c "$list" ) || rc=6
  [ -n "$tmp" ] && { "${sudo[@]}" umount "$tmp"; rmdir "$tmp"; }
  [ "$rc" -eq 0 ] && echo "OK: SW-REPORTS files (key, operator.conf, SHAMANWIPE.txt) match the image ($mp)." || echo "ERROR: SW-REPORTS files do not match the image" >&2
  return $rc
}

# Verify an already written device (no writing)
verify() {
  local dev=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --image) IMG="$2"; shift 2 ;;
      -*) refuse "unknown option $1" ;;
      *) dev="$1"; shift ;;
    esac
  done
  [ -s "$IMG" ] || refuse "$IMG missing"
  ( cd "$(dirname "$IMG")" && shasum -a 256 -c "$(basename "$IMG").sha256" ) >/dev/null || refuse "image checksum mismatch"
  local raw
  case "$(uname)" in
    Darwin) [[ "$dev" =~ ^/dev/disk[0-9]+$ ]] || refuse "specify the whole disk /dev/diskN"; raw="/dev/r${dev#/dev/}" ;;
    Linux) [[ "$dev" =~ ^/dev/sd[a-z]+$ ]] || refuse "specify the whole disk /dev/sdX"; raw="$dev" ;;
    *) refuse "unsupported system $(uname)" ;;
  esac
  local sudo=(); [ -r "$raw" ] || sudo=(sudo)
  verify_media "$dev" "$raw" "${sudo[@]}"
}

case "${1:-}" in
  image) shift; image "$@" ;;
  write) shift; write "$@" ;;
  verify) shift; verify "$@" ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
