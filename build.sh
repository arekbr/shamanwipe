#!/usr/bin/env bash
# Builds the ShamanWipe ISO on a Mac: Colima (profile "shamanwipe", vz + Rosetta) + a Debian 13 amd64 container.
# Usage: ./build.sh            -> out/shamanwipe-<version>-amd64.iso + .sha256 + .packages
# Cleanup after the build:  colima stop shamanwipe   (or: colima delete shamanwipe - removes the VM and the build cache)
set -euo pipefail
cd "$(dirname "$0")"

PROFILE=shamanwipe
CTX="colima-${PROFILE}"
VERSION="$(cat VERSION)"

CONTEXT_BEFORE="$(docker context show 2>/dev/null || true)"
if ! colima status "$PROFILE" >/dev/null 2>&1; then
  echo ">> starting Colima ($PROFILE)"
  # --activate=false: do not change the user's default Docker context (without it Colima switches it)
  colima start "$PROFILE" --activate=false --vm-type vz --vz-rosetta --cpu 8 --memory 12 --disk 60
fi
[ "$(docker context show 2>/dev/null || true)" = "$CONTEXT_BEFORE" ] || { echo "ERROR: the default Docker context changed" >&2; exit 9; }

mkdir -p out
echo ">> building in an amd64 container (version $VERSION)"
# --privileged: live-build mounts /proc, /sys, /dev in the chroot.
# Volume sw-cache: .deb packages kept between builds (live-build cache/).
docker --context "$CTX" run --rm --privileged --platform linux/amd64 \
  -v "$PWD":/src:ro \
  -v "$PWD/out":/out \
  -v sw-cache:/cache \
  -e SW_VERSION="$VERSION" \
  debian:trixie /src/scripts/build-in-container.sh

echo ">> done:"
ls -l out/shamanwipe-"$VERSION"-amd64.*
( cd out && shasum -a 256 -c "shamanwipe-$VERSION-amd64.iso.sha256" )
