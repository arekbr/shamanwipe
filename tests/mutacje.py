"""Falsyfikator testów doboru („każdy przypadek umie być czerwony”).

Wprowadza do KOPII programu po jednym celowym błędzie i sprawdza, że tests/test_dobor.py go wykrywa.
Uruchomienie: python3 -I tests/mutacje.py   → kod 0 tylko, gdy KAŻDA mutacja wywróciła testy.
Nic nie mutuje w repo (kopie w katalogu tymczasowym, usuwane na końcu).
"""
import os
import pathlib
import subprocess
import sys
import tempfile

TU = pathlib.Path(__file__).resolve().parent
ORYG = (TU.parent / 'src' / 'shamanwipe').read_text()

MUTACJE = [
    ('SE przed Sanitize (kolejność tabeli)',
     "        if s.get('crypto'):\n            wynik.append('ata-sanitize-crypto')",
     "        if b.get('enhanced') and False: pass\n        wynik.append('ata-se-enhanced') if b.get('enhanced') and b.get('obslugiwane') else None\n        if s.get('crypto'):\n            wynik.append('ata-sanitize-crypto')"),
    ('Block Erase dozwolony na HDD',
     "        if s.get('block') and nosnik != 'HDD':\n            wynik.append('ata-sanitize-block')",
     "        if s.get('block'):\n            wynik.append('ata-sanitize-block')"),
    ('SSD bez odpowiedzi na IDENTIFY po SE = sukces',
     "        return 'UNCONFIRMED', L('polecenie zakończone kodem 0, ale dysk nie odpowiada",
     "        return 'OK', L('polecenie zakończone kodem 0, ale dysk nie odpowiada"),
    ('realokowane nie dają zastrzeżenia',
     "    if tylko_host and (d.get('smart_przed', {}).get('realokowane') or 0) > 0:",
     "    if False and tylko_host and (d.get('smart_przed', {}).get('realokowane') or 0) > 0:"),
    ('znacznik identyczny jak przed = OK',
     "            else:\n                przetrwaly += 1",
     "            else:\n                ok += 1"),
    ('NVMe Format SES=2 jako CLEAR',
     "    'nvme-format-crypto':      ('PURGE',",
     "    'nvme-format-crypto':      ('CLEAR',"),
    ('dysk zablokowany hasłem → nadpis zamiast odmowy',
     "            return [], uwagi, L('Dysk ZABLOKOWANY hasłem ATA",
     "            uwagi.append('x'); 0 and L('Dysk ZABLOKOWANY hasłem ATA"),
    ('mostek USB bez SAT dostaje klasę CLEAR zamiast NONE',
     "        plan['klasa'] = 'NONE'",
     "        plan['klasa'] = plan['klasa']"),
    ('HPA/DCO nieprzywrócone: nadpis hosta znowu dozwolony jako rezerwa',
     "                    plan['zapasowe'] = [m for m in plan.get('zapasowe', []) if METODY[m][3] != 'host']",
     "                    pass"),
    ('przetrwałe dane przy stanie niepotwierdzonym dają UNCONFIRMED zamiast FAILED',
     "            if przetrwaly:  # dowód",
     "            if False:  # dowód"),
    ('Security Erase uruchamiany na zamrożonym dysku (bramka przed hasłem ATA)',
     "        if ((a0 or {}).get('bezpieczenstwo') or {}).get('zamrozone') is not False:",
     "        if False:"),
    ('nieznany stan frozen po uśpieniu traktowany jak odmrożony',
     "        if zamr is not False:  # nieznany stan po uśpieniu traktowany jak „nadal zamrożony”",
     "        if zamr:"),
    ('dysk nadal zamrożony: Security Erase zostaje w rezerwach',
     "            z.d['plan']['zapasowe'] = nowe  # SE na zamrożonym dysku nie wraca też jako rezerwa",
     "            pass"),
    ('sprawdzenie na sprzęcie per rodzina: cała rodzina ata uznana za sprawdzoną (SE bez adnotacji)',
     "if METODY[k][3] != 'host' and k not in ZWERYFIKOWANE_NA_SPRZECIE})",
     "if METODY[k][3] not in ('host', 'ata')})"),
]


def main():
    zle = 0
    with tempfile.TemporaryDirectory() as tmp:
        for nazwa, stare, nowe in MUTACJE:
            n = ORYG.count(stare)
            if n != 1:
                print(f'MUTACJA NIEWAŻNA (wzorzec {n}×): {nazwa}')
                zle += 1
                continue
            plik = os.path.join(tmp, 'shamanwipe')
            pathlib.Path(plik).write_text(ORYG.replace(stare, nowe))
            p = subprocess.run([sys.executable, '-I', str(TU / 'test_dobor.py')], env=dict(os.environ, SW_SRC=plik),
                               capture_output=True, text=True)
            wykryta = p.returncode != 0
            print(f'{"WYKRYTA " if wykryta else "PRZESZŁA"}  {nazwa}' + ('' if wykryta else '  ← testy jej NIE widzą'))
            zle += 0 if wykryta else 1
    print(f'\nmutacje: {len(MUTACJE)}, niewykryte/nieważne: {zle}')
    return 1 if zle else 0


if __name__ == '__main__':
    sys.exit(main())
