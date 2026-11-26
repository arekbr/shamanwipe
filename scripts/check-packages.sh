#!/bin/sh
# Image content gate. Usage: check-packages.sh <.packages file>  -> 0 = OK, 3 = required package missing, 2 = forbidden package present, 4 = list missing or empty.
# check-packages.sh --required | --forbidden  -> prints the list (single source for the falsifier tests/test_check_packages.sh).
REQUIRED="openseachest hdparm nvme-cli sg3-utils smartmontools nwipe sedutil mmc-utils python3-reportlab
          fonts-dejavu-core openssl whiptail dmidecode util-linux"
# Nothing that assembles arrays or unlocks volumes from the disks being erased
FORBIDDEN="mdadm lvm2 cryptsetup cryptsetup-bin dmraid"
case "${1:-}" in
  --required) echo $REQUIRED; exit 0 ;;
  --forbidden) echo $FORBIDDEN; exit 0 ;;
esac
P="$1"
[ -s "$P" ] || { echo "ERROR: package list missing or empty: $P" >&2; exit 4; }
RC=0
for p in $REQUIRED; do
  grep -qE "^${p}(:[a-z0-9]+)?[[:space:]]" "$P" || { echo "ERROR: required package missing: $p" >&2; RC=3; }
done
for p in $FORBIDDEN; do
  grep -qE "^${p}(:[a-z0-9]+)?[[:space:]]" "$P" && { echo "ERROR: forbidden package in the image: $p" >&2; RC=2; }
done
exit $RC
