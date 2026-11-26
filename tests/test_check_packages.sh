#!/bin/sh
# Falsifier of the image content gate: the gate must be RED on a broken list and green on the real one.
# Usage: tests/test_check_packages.sh [.packages file]   (default: out/shamanwipe-<version>-amd64.packages)
# Works on copies in a temporary directory; does not change the lists in out/. Takes the package lists from the gate itself.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GATE="$ROOT/scripts/check-packages.sh"
LIST="${1:-$ROOT/out/shamanwipe-$(cat "$ROOT/VERSION")-amd64.packages}"
[ -s "$LIST" ] || { echo "ERROR: list missing: $LIST (run ./build.sh first)"; exit 2; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILED=0; N=0
REQ="$(sh "$GATE" --required)"; FORB="$(sh "$GATE" --forbidden)"
NREQ=$(echo $REQ | wc -w | tr -d " "); NFORB=$(echo $FORB | wc -w | tr -d " ")

expect() {  # expect <expected_rc> <description> <file>
  N=$((N + 1))
  sh "$GATE" "$3" >/dev/null 2>"$T/err"; rc=$?
  if [ "$rc" -eq "$1" ]; then echo "OK   $2 (rc=$rc)"; else echo "ERROR $2: rc=$rc, expected $1 - $(head -1 "$T/err")"; FAILED=$((FAILED + 1)); fi
}

expect 0 "real list" "$LIST"
for p in $REQ; do  # each required package separately: copy of the list without its line -> 3
  grep -vE "^${p}(:[a-z0-9]+)?[[:space:]]" "$LIST" > "$T/without-$p"
  if cmp -s "$LIST" "$T/without-$p"; then echo "ERROR without $p: copy identical to the original (package was not there?)"; FAILED=$((FAILED + 1)); N=$((N + 1)); continue; fi
  expect 3 "without $p" "$T/without-$p"
done
for p in $FORB; do  # each forbidden package separately: copy of the list with an added line -> 2
  { cat "$LIST"; printf '%s\t1.0-1\n' "$p"; } > "$T/with-$p"
  expect 2 "with $p" "$T/with-$p"
done
{ cat "$LIST"; printf 'mdadm:amd64\t4.4-1\n'; } > "$T/with-mdadm-arch"
expect 2 "with mdadm:amd64 (name with architecture)" "$T/with-mdadm-arch"
expect 4 "empty list" /dev/null
# Falsifier of the falsifier: the number of cases follows from the gate's lists; 0 required = the test checked nothing
[ "$NREQ" -ge 10 ] || { echo "ERROR: the gate returned only $NREQ required packages"; FAILED=$((FAILED + 1)); }
[ "$N" -eq $((NREQ + NFORB + 3)) ] || { echo "ERROR: ran $N cases, expected $((NREQ + NFORB + 3))"; FAILED=$((FAILED + 1)); }
echo "RESULT: $((N - FAILED))/$N matching (required $NREQ, forbidden $NFORB)"
[ "$FAILED" -eq 0 ]
