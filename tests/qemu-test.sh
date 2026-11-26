#!/usr/bin/env bash
# Testy ISO shamanwipe w QEMU na macOS (G2, G3, G4, G5, G9).
# Uzycie: tests/qemu-test.sh [wszystko | g2 | g3 | g9a | g9b | lista po przecinku]
# Kroki: suma ISO → obraz pendrive'a TESTOWY (klucz z losowym hasłem testowym, tests/wyniki/qemu/obrazy; keys/ nietknięte)
#        → scenariusze tests/qemu_test.py → hasło testowe i kopie obrazów usuwane na końcu (trap).
# Wymaga: qemu-system-x86_64 (brew), Colima "shamanwipe" (budowa obrazu pendrive'a), /opt/homebrew/bin/openssl (Ed25519).
set -euo pipefail
cd "$(dirname "$0")/.."
O=tests/wyniki/qemu/obrazy
mkdir -p "$O"
WERSJA="$(cat VERSION)"
( cd out && shasum -a 256 -c "shamanwipe-${WERSJA}-amd64.iso.sha256" )
sprzataj() {
  rm -f "$O/haslo-testowe.txt" "$O"/g3-pendrive.img "$O"/g9b-pendrive.img "$O"/g9a-pendrive.img "$O"/g*-*.img
  pgrep -f 'swq-' >/dev/null && pkill -f 'swq-' || true
}
trap sprzataj EXIT
( umask 077; openssl rand -hex 12 > "$O/haslo-testowe.txt" )
bash scripts/make-usb.sh image --reports-mib 256 --out-dir "$PWD/$O" < "$O/haslo-testowe.txt" | grep -E '^(OK|ERROR|REFUSED|shamanwipe)'
python3 -I tests/qemu_test.py "${1:-wszystko}"
