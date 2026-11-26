#!/usr/bin/env bash
# Testy na urządzeniach loop w kontenerze amd64 (profil Colimy "shamanwipe"). Wynik: tests/wyniki/wyniki-urzadzenia.json
# + kopia podpisanego raportu do weryfikacji OpenSSL na macOS. Kontener --rm, loopy odłączane przez harness.
# Uzycie: tests/test_urzadzenia.sh [wszystko|urzadzenia|konsole]   (konsole = tests/harness_konsole.py, wyścig tty1/ttyS0)
set -euo pipefail
cd "$(dirname "$0")/.."
CO="${1:-wszystko}"
mkdir -p tests/wyniki
docker --context colima-shamanwipe run --rm --privileged --platform linux/amd64 -e CO="$CO" -e SW_SRC="${SW_SRC:-}" -e SW_LANG=pl \
  -v "$PWD":/src:ro -v "$PWD/tests/wyniki":/out-testy debian:trixie bash -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 python3-reportlab fonts-dejavu-core openssl \
      dosfstools util-linux smartmontools hdparm nvme-cli sg3-utils dmidecode pciutils whiptail ncurses-base >/dev/null
    RC=0
    if [ "$CO" != konsole ]; then python3 -I /src/tests/harness_urzadzenia.py || RC=$?; fi
    if [ "$CO" != urzadzenia ]; then python3 -I /src/tests/harness_konsole.py || RC=$?; fi
    exit $RC'
