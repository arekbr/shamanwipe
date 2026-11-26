#!/usr/bin/env bash
# Falsyfikator testów konsol (tests/harness_konsole.py): każda mutacja psuje jedną własność programu i MUSI wywrócić
# harness (rc != 0) w oczekiwanym teście. Mutanty w tests/wyniki/mutacje-konsole/, wynik w .../wynik.txt.
# Uzycie: tests/mutacje_konsole.sh      (ok. 75 s na mutację; Colima "shamanwipe"
set -uo pipefail
cd "$(dirname "$0")/.."
M=tests/wyniki/mutacje-konsole
rm -rf "$M"; mkdir -p "$M"
ZLE=0; N=0
mutuj() {  # mutuj <nazwa> <oczekiwany czerwony test (regex)> <python: zamiana stary->nowy>
  local nazwa="$1" oczek="$2" stary="$3" nowy="$4"
  N=$((N + 1))
  python3 -I - "$nazwa" "$stary" "$nowy" <<'EOF' || { echo "BLAD $1: wzorzec nie występuje w programie"; ZLE=$((ZLE + 1)); return; }
import sys
nazwa, stary, nowy = sys.argv[1:4]
s = open('src/shamanwipe', encoding='utf-8').read()
if s.count(stary) != 1:
    sys.exit(1)
open(f'tests/wyniki/mutacje-konsole/{nazwa}', 'w', encoding='utf-8').write(s.replace(stary, nowy))
EOF
  SW_SRC="/src/$M/$nazwa" bash tests/test_urzadzenia.sh konsole > "$M/$nazwa.log" 2>&1
  local rc=$?
  local czerwone; czerwone=$(grep -a '^BŁĄD' "$M/$nazwa.log" | cut -c6-90 | tr '\n' ';')
  if [ "$rc" -ne 0 ] && grep -aqE "^BŁĄD .*(${oczek})" "$M/$nazwa.log"; then
    echo "OK   $nazwa wykryta (czerwone: $czerwone)"
  else
    echo "BLAD $nazwa NIEWYKRYTA albo nie tam (rc=$rc, czerwone: $czerwone)"; ZLE=$((ZLE + 1))
  fi
}
{
mutuj M1-bez-surowego-terminala 'R2 \[Ctrl\+C\]|R2w' \
  'nowe[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)' 'pass'
mutuj M2-podglad-nie-dostarcza 'R2 \[Enter\]' \
  "open(plik_przerwania(a['id']), 'w').close()" 'pass'
mutuj M3-bez-pierwszenstwa 'R4 pierwszeństwo' \
  '    if konsola() != pref:' '    if False:'
mutuj M4-g13-bez-w-toku 'R6 operacja z żywym' \
  "if not (biez and w.get('boot_id') == biez and proces_zyje(w.get('pid')))]" 'if True]'
mutuj M5-haki-w-produkcji 'R7' \
  'return os.environ.get(nazwa, domyslnie) if TRYB_TESTOWY else domyslnie' 'return os.environ.get(nazwa, domyslnie)'
mutuj M6-wylacz-bez-straznika 'R5 „Wyłącz' \
  "        if wybor == '6':
            if wlasciciel_blokady():" "        if wybor == '6':
            if False:"
mutuj M7-wlasciciel-zawsze-brak 'R2 \[Enter\]|R4' \
  '                return int(p[4])' '                return None'
mutuj M8-przejecie-mimo-przerwania 'R4 po przerwaniu' \
  '        while wlasciciel_blokady() is None and not os.path.exists(PLIK_AUTOMAT):
            if instancja_zyje(pref):
                t0 = time.time()
            elif time.time() - t0 >= PRZEJECIE_AUTOMATU_S:
                break
            time.sleep(0.5)
        if wlasciciel_blokady() is not None or os.path.exists(PLIK_AUTOMAT):' '        while wlasciciel_blokady() is None:
            if instancja_zyje(pref):
                t0 = time.time()
            elif time.time() - t0 >= PRZEJECIE_AUTOMATU_S:
                break
            time.sleep(0.5)
        if wlasciciel_blokady() is not None:'
echo "WYNIK MUTACJI KONSOL: $((N - ZLE))/$N wykrytych"
} | tee "$M/wynik.txt"
! grep -q '^BLAD' "$M/wynik.txt"
