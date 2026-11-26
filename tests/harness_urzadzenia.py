"""Testy na urządzeniach (loop) — uruchamiane WEWNĄTRZ kontenera amd64 przez tests/test_urzadzenia.sh.

Pokrywa: G4 (nadpis + kontrola + dyski-oszusty), G5 (podpis, podmiana 1 bajtu), G6 (ochrona, potwierdzenie,
podmiana dysku), G9 (AUTOMAT: odmowy, przebieg, „nic nie skasowano”), G12 (bajty), G13 (dziennik), EN (interfejs
angielski, stały schemat raportu). Domyślnie interfejs polski (SW_LANG=pl z tests/test_urzadzenia.sh).
Mutuje WYŁĄCZNIE pliki obrazów w /work i urządzenia loop, które sam podłączył (SW_TEST_TYLKO_LOOP=1 —
program nie widzi dysków maszyny Colimy). Po zakończeniu odłącza swoje loopy.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

W = pathlib.Path('/work')
SRC = os.environ.get('SW_SRC') or '/src/src/shamanwipe'  # SW_SRC: tests/mutacje_konsole.sh podmienia program
MNT = '/mnt/sw-reports'
ENV = dict(os.environ, SW_TEST_TYLKO_LOOP='1', SW_MNT_RAPORTY=MNT, SW_RUN='/run/sw-test', SW_ODLICZANIE='2')
os.environ.update(ENV)
WYNIKI = []
LOOPY = []
MB = 1024 * 1024


def sh(*cmd, wejscie=None, ok=(0,)):
    p = subprocess.run(list(cmd), capture_output=True, text=True, input=wejscie, env=ENV)
    if p.returncode not in ok:
        raise RuntimeError(f'{cmd}: rc={p.returncode} {p.stderr[-400:]}')
    return p


def sprawdz(nazwa, warunek, szczegol=''):
    WYNIKI.append((nazwa, bool(warunek), szczegol))
    print(('OK   ' if warunek else 'BŁĄD ') + nazwa + (f'  [{szczegol}]' if szczegol and not warunek else ''), flush=True)


def obraz(nazwa, mb, losowy=True):
    p = W / nazwa
    with open(p, 'wb') as f:
        for _ in range(mb):
            f.write(os.urandom(MB) if losowy else bytes(MB))
    return p


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for k in iter(lambda: f.read(MB), b''):
            h.update(k)
    return h.hexdigest()


def same_zera(p):
    z = bytes(MB)
    with open(p, 'rb') as f:
        for k in iter(lambda: f.read(MB), b''):
            if k != z[:len(k)]:
                return False
    return True


def podlacz(p):
    dev = sh('losetup', '-f', '--show', str(p)).stdout.strip()
    LOOPY.append(dev)
    return dev


def odlacz(dev):
    subprocess.run(['losetup', '-d', dev])
    if dev in LOOPY:
        LOOPY.remove(dev)


def sw_cli(*args, ok=(0, 3, 4, 5)):
    return sh(sys.executable, '-I', SRC, *args, ok=ok)


def modul():
    l = importlib.machinery.SourceFileLoader('shamanwipe_test', SRC)
    s = importlib.util.spec_from_loader('shamanwipe_test', l)
    m = importlib.util.module_from_spec(s)
    l.exec_module(m)
    return m


def ostatni_raport():
    kat = sorted(pathlib.Path(MNT, 'reports').iterdir(), key=lambda x: x.stat().st_mtime)[-1]
    return kat, json.loads((kat / 'report.json').read_text())


def przygotuj_raporty():
    img = obraz('sw-reports.img', 64, losowy=False)
    dev = podlacz(img)
    sh('mkfs.vfat', '-n', 'SW-REPORTS', dev)
    os.makedirs(MNT, exist_ok=True)
    sh('mount', dev, MNT)
    k = pathlib.Path(MNT, 'key')
    k.mkdir()
    # Klucz TESTOWY bez hasła (wartość testowa, powstaje tu i ginie z kontenerem)
    sh('openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(k / 'shamanwipe-signing.pem'))
    sh('openssl', 'pkey', '-in', str(k / 'shamanwipe-signing.pem'), '-pubout', '-out', str(k / 'shamanwipe-signing.pub.pem'))
    pathlib.Path(MNT, 'operator.conf').write_text('name=Operator Testowy\ntitle=test\norganization=Shamans of Silicon test\nlocation=kontener\ncontact=brak\n')
    return dev


def main():
    W.mkdir(exist_ok=True)
    for i in range(64):  # w kontenerze bez udev węzły loop trzeba czasem utworzyć
        if not os.path.exists(f'/dev/loop{i}'):
            subprocess.run(['mknod', f'/dev/loop{i}', 'b', '7', str(i)])
    m = modul()

    # --- G9a: AUTOMAT bez SW-REPORTS = odmowa
    sprawdz('G9 AUTOMAT bez SW-REPORTS odmawia (rc 5)', m.tryb_automat({'auto': 'standard'}) == 5)

    dev_rap = przygotuj_raporty()

    # --- G9b: AUTOMAT bez rozpoznanego nośnika startowego = odmowa
    cel_a = obraz('cel-a.img', 64)
    dev_a = podlacz(cel_a)
    sha_a = sha(cel_a)
    sprawdz('G9 AUTOMAT bez nośnika startowego odmawia (rc 5)', m.tryb_automat({'auto': 'standard'}) == 5)
    sprawdz('G9 po odmowie cel nietknięty', sha(cel_a) == sha_a)

    # --- G4/G12/G5: kasuj nadpis + dysk kontrolny
    kontrola = obraz('kontrola.img', 64)
    dev_k = podlacz(kontrola)
    sha_k = sha(kontrola)
    lista = sw_cli('lista', '--json')
    lj = json.loads(lista.stdout)
    sprawdz('G3 lista widzi loopy celu i kontroli', {dev_a, dev_k} <= {d['sciezka'] for d in lj}, lista.stdout[-300:])
    sprawdz('G6 SW-REPORTS chroniony w liście', any(d['sciezka'] == dev_rap and d['chroniony'] for d in lj))
    p = sw_cli('kasuj', '--dysk', dev_a, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1')
    kat, r = ostatni_raport()
    sprawdz('G4 kasuj nadpis rc=0', p.returncode == 0, p.stdout[-500:])
    sprawdz('G4 cel: każdy bajt = 0', same_zera(cel_a))
    sprawdz('G4 dysk kontrolny nietknięty (SHA-256)', sha(kontrola) == sha_k)
    d0 = r['disks'][0]
    sprawdz('G12 bytes_verified = rozmiar = bytes_written', d0['bytes_verified'] == d0['device_size_bytes'] == d0['bytes_written'] == 64 * MB,
            f"{d0['bytes_verified']} {d0['device_size_bytes']} {d0['bytes_written']}")
    sprawdz('G10 status nadpisu nośnika nieznanego = Z ZASTRZEŻENIEM', d0['status'] == 'ERASED_WITH_WARNINGS', d0['status'])
    sprawdz('SCHEMAT raport kasuj: tylko klucze schematu (bez kluczy wewnętrznych)', m.klucze_spoza_schematu(r) == [],
            str(m.klucze_spoza_schematu(r)[:10]))
    sprawdz('SCHEMAT raport PL: language=pl, kody statusów stałe', r['language'] == 'pl' and set(r['summary']) == set(m.STATUSY), str(r['summary']))
    schemat_pl = sorted(r) + sorted(d0)
    sprawdz('G5 komplet plików raportu', all((kat / f).exists() for f in ('report.pdf', 'report.json', 'report.csv', 'report.xml',
                                                                           'MANIFEST.sha256', 'MANIFEST.sha256.sig', 'public-key.pem')),
            str(sorted(x.name for x in kat.iterdir())))
    sprawdz('G5 raport podpisany', r['signature']['signed'] is True)
    sprawdz('G5 weryfikuj = WAŻNY (rc 0)', sw_cli('weryfikuj', str(kat), ok=(0, 1, 2)).returncode == 0)
    shutil.copytree(kat, '/out-testy/raport-podpisany', dirs_exist_ok=True)
    for plik in ('report.pdf', 'report.json', 'report.csv', 'report.xml', 'MANIFEST.sha256', 'MANIFEST.sha256.sig'):
        kopia = W / f'tamper-{plik}'
        shutil.copytree(kat, kopia)
        b = bytearray((kopia / plik).read_bytes())
        b[len(b) // 2] ^= 0x01
        (kopia / plik).write_bytes(bytes(b))
        rc = sw_cli('weryfikuj', str(kopia), ok=(0, 1, 2)).returncode
        sprawdz(f'G5 zmiana 1 bajtu w {plik} → NIEWAŻNY (rc 2)', rc == 2, f'rc={rc}')
    tekst = (kat / 'report.json').read_text()
    sprawdz('G5 raport nie zawiera treści dysku (tylko SHA-256)', 'sha256' not in tekst.lower() or '"jednolita"' not in tekst)

    # --- G13: dziennik operacji
    dz = pathlib.Path(MNT, 'operations-log.jsonl').read_text().splitlines()
    stany = [json.loads(x)['state'] for x in dz]
    sprawdz('G13 dziennik: start i koniec operacji', stany.count('start') >= 1 and stany.count('start') == stany.count('end'), str(stany))
    with open(pathlib.Path(MNT, 'operations-log.jsonl'), 'a') as f:
        f.write(json.dumps({'id': 'TEST-urwany', 'state': 'start', 'device': '/dev/sdz', 'ata_password_set': True, 'time': 'x'}) + '\n')
    sprawdz('G13 niedokończona operacja wykryta', any(w['id'] == 'TEST-urwany' for w in m.niedokonczone_operacje()))
    with open(pathlib.Path(MNT, 'operations-log.jsonl'), 'a') as f:
        f.write(json.dumps({'id': 'TEST-urwany', 'state': 'end'}) + '\n')

    # --- G6: ochrona i potwierdzenie
    iso = obraz('nosnik-iso.img', 32, losowy=False)
    dev_iso = podlacz(iso)
    sh('mkfs.vfat', '-n', 'SHAMANWIPE', dev_iso)
    sha_iso = sha(iso)
    p = sw_cli('kasuj', '--dysk', dev_iso, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1')
    sprawdz('G6 nośnik z etykietą SHAMANWIPE: odmowa (rc 3)', p.returncode == 3 and 'CHRONIONY' in p.stdout, p.stdout[-300:])
    sprawdz('G6 nośnik nietknięty', sha(iso) == sha_iso)
    p = sw_cli('kasuj', '--dysk', dev_rap, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1')
    sprawdz('G6 zamontowany SW-REPORTS: odmowa (rc 3)', p.returncode == 3, p.stdout[-300:])
    p = sw_cli('kasuj', '--dysk', dev_k, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 2')
    sprawdz('G6 złe potwierdzenie: odmowa (rc 3)', p.returncode == 3 and sha(kontrola) == sha_k)

    # --- EN: interfejs angielski (SW_LANG=en), polecenia angielskie, ten sam schemat raportu co po polsku
    en = dict(ENV, SW_LANG='en')
    cel_en = obraz('cel-en.img', 16)
    dev_en = podlacz(cel_en)
    sha_en = sha(cel_en)
    p = subprocess.run([sys.executable, '-I', SRC, 'erase', '--disk', dev_en, '--profile', 'overwrite', '--confirm', 'ERASE 2'],
                       capture_output=True, text=True, env=en)
    sprawdz('EN złe potwierdzenie: REFUSED (rc 3), dysk nietknięty', p.returncode == 3 and 'REFUSED' in p.stdout and sha(cel_en) == sha_en,
            p.stdout[-200:])
    p = subprocess.run([sys.executable, '-I', SRC, 'erase', '--disk', dev_en, '--profile', 'overwrite', '--confirm', 'ERASE 1'],
                       capture_output=True, text=True, env=en)
    kat_en, r_en = ostatni_raport()
    sprawdz('EN erase --confirm "ERASE 1": rc 0, każdy bajt = 0', p.returncode == 0 and same_zera(cel_en), p.stdout[-300:])
    sprawdz('EN raport: language=en, status ERASED_WITH_WARNINGS, technika po angielsku',
            r_en['language'] == 'en' and r_en['disks'][0]['status'] == 'ERASED_WITH_WARNINGS'
            and r_en['disks'][0]['technique'].startswith('Single-pass zero overwrite'), json.dumps(r_en['disks'][0], ensure_ascii=False)[:300])
    sprawdz('EN wynik na ekranie po angielsku (RESULT, ERASED WITH WARNINGS)', 'RESULT:' in p.stdout and 'ERASED WITH WARNINGS' in p.stdout,
            p.stdout[-300:])
    sprawdz('SCHEMAT EN = PL (te same klucze raportu i dysku)', sorted(r_en) + sorted(r_en['disks'][0]) == schemat_pl)
    sprawdz('SCHEMAT raport EN bez kluczy wewnętrznych', m.klucze_spoza_schematu(r_en) == [], str(m.klucze_spoza_schematu(r_en)[:10]))
    csv_en = (kat_en / 'report.csv').read_text(encoding='utf-8-sig').splitlines()[0]
    sprawdz('SCHEMAT CSV: nagłówek angielski', csv_en.startswith('report;computer_serial;device;model;serial_number'), csv_en)
    sprawdz('SCHEMAT XML: korzeń sanitization_report', '<sanitization_report>' in (kat_en / 'report.xml').read_text())
    p = subprocess.run([sys.executable, '-I', SRC, 'verify', str(kat_en)], capture_output=True, text=True, env=en)
    sprawdz('EN verify = VALID (rc 0)', p.returncode == 0 and p.stdout.startswith('VALID'), p.stdout[-200:])
    sprawdz('EN raport ma PDF', (kat_en / 'report.pdf').exists() and (kat_en / 'report.pdf').stat().st_size > 1000)
    cel_pl2 = obraz('cel-pl2.img', 16)
    dev_pl2 = podlacz(cel_pl2)
    p = sw_cli('kasuj', '--dysk', dev_pl2, '--profil', 'nadpis', '--potwierdzam', 'ERASE 1')
    sprawdz('PL: potwierdzenie w drugim języku („ERASE 1”) przyjęte', p.returncode == 0 and same_zera(cel_pl2), p.stdout[-200:])
    odlacz(dev_en)
    odlacz(dev_pl2)

    # --- G6: podmiana dysku między planem a wykonaniem
    cel_b = obraz('cel-b.img', 64)
    dev_b = podlacz(cel_b)
    sha_b = sha(cel_b)
    obcy = obraz('obcy.img', 48)
    sha_obcy = sha(obcy)
    flaga = W / 'podmiana-go'
    proc = subprocess.Popen([sys.executable, '-I', SRC, 'kasuj', '--dysk', dev_b, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1'],
                            env=dict(ENV, SW_TEST_PODMIANA=str(flaga)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    linia = proc.stdout.readline()
    while 'SWAP: waiting' not in linia and linia:
        linia = proc.stdout.readline()
    subprocess.run(['losetup', '-d', dev_b])
    sh('losetup', dev_b, str(obcy))
    flaga.touch()
    out, _ = proc.communicate(timeout=300)
    kat, r = ostatni_raport()
    sprawdz('G6 podmiana dysku → NIEPOWODZENIE z „ZMIANA TOŻSAMOŚCI”', r['disks'][0]['status'] == 'FAILED'
            and any('ZMIANA TOŻSAMOŚCI' in u for u in r['disks'][0]['notes']), json.dumps(r['disks'][0].get('notes'), ensure_ascii=False))
    sprawdz('G6 podstawiony dysk nietknięty', sha(obcy) == sha_obcy)
    sprawdz('G6 pierwotny dysk nietknięty', sha(cel_b) == sha_b)
    odlacz(dev_b)

    # --- G4: dysk-oszust 1 — nadpis gubi zapisy w oknie
    cel_c = obraz('cel-c.img', 64)
    dev_c = podlacz(cel_c)
    m = modul()
    dyski = m.inwentarz()
    lista = m.plan_dla_wszystkich(dyski, 'nadpis', [dev_c])
    oryg = m.Zadanie._zapis_bloku
    m.Zadanie._zapis_bloku = lambda self, u, buf, poz, dl: dl if 8 * MB <= poz < 12 * MB else oryg(self, u, buf, poz, dl)
    zad, _ = m.kasuj(lista, 'nadpis')
    m.Zadanie._zapis_bloku = oryg
    sprawdz('G4 oszust (nadpis pomija 4 MiB) → program sam: NIEPOWODZENIE', zad[0].status == 'FAILED',
            f'{zad[0].status} {zad[0].weryfikacja}')

    # --- G4/G11: dysk-oszust 2 — „kasowanie sprzętowe” bez efektu; kontrola dodatnia: kasowanie, które zeruje
    for nazwa, zeruj, oczek in (('atrapa bez efektu', False, 'FAILED'), ('atrapa zerująca (kontrola dodatnia)', True, 'ERASED')):
        img = obraz(f'nvme-{int(zeruj)}.img', 64)
        dev = podlacz(img)
        m = modul()
        d = [x for x in m.inwentarz() if x['sciezka'] == dev][0]
        d.update(interfejs='nvme', typ_nosnika='NVMe SSD', serial='', serial_zrodlo='NVMe Identify',
                 nvme={'kontroler': '/dev/nvme-atrapa', 'liczba_ns': 1, 'sanitize': {}, 'format_obslugiwany': True, 'format_crypto': False})
        d['plan'] = {'kroki': ['nvme-format-user'], 'zapasowe': [], 'uwagi': [], 'przygotowanie': [], 'mozliwe': True}
        m.uzupelnij_plan(d['plan'], d)
        d['tozsamosc'] = m.tozsamosc(d)
        m.odczytaj_tozsamosc = lambda dd: {'serial': '', 'rozmiar_b': m.rozmiar_urzadzenia(dd['sciezka'])}

        def atrapa(self, ses, zeruj=zeruj):
            if zeruj:
                with open(self.d['sciezka'], 'r+b') as f:
                    for _ in range(64):
                        f.write(bytes(MB))
                    f.flush()
                    os.fsync(f.fileno())
            return self._krok('nvme-format', 0, 'atrapa')
        m.Zadanie.nvme_format = atrapa
        zad, _ = m.kasuj([d], 'standard')
        sprawdz(f'G11 sprzętowe: {nazwa} → {oczek}', zad[0].status == oczek, f'{zad[0].status} {zad[0].weryfikacja}')
        odlacz(dev)

    # --- G9c: AUTOMAT pełny przebieg (nośnik SHAMANWIPE obecny, cele: kontrola + cel-c)
    m = modul()
    for dev in (dev_a,):
        odlacz(dev)
    rc = m.tryb_automat({'auto': 'nadpis'})
    kat, r = ostatni_raport()
    cele = {d['device'] for d in r['disks']}
    sprawdz('G9 AUTOMAT rc=0 i raport trybu automat', rc == 0 and r['mode'] == 'auto', f'rc={rc} mode={r["mode"]}')
    sprawdz('SCHEMAT raport AUTOMATU bez kluczy wewnętrznych', m.klucze_spoza_schematu(r) == [], str(m.klucze_spoza_schematu(r)[:10]))
    sprawdz('G9 AUTOMAT skasował cele (kontrola, cel-c), nie dotknął SHAMANWIPE/SW-REPORTS',
            cele == {dev_k, dev_c} and sha(iso) == sha_iso and same_zera(kontrola) and same_zera(cel_c), str(cele))
    sprawdz('G9 AUTOMAT: pominięte dyski w raporcie z powodem', {p['device'] for p in r['skipped']} >= {dev_iso, dev_rap})

    # --- G9d: AUTOMAT bez celów → „NIC NIE SKASOWANO”
    odlacz(dev_k)
    odlacz(dev_c)
    rc = m.tryb_automat({'auto': 'standard'})
    kat, r = ostatni_raport()
    sprawdz('G9 AUTOMAT bez celów → raport NIC NIE SKASOWANO', rc == 0 and r.get('nothing_erased') and r['disks'] == [],
            f'rc={rc} {r.get("nothing_erased")}')
    sprawdz('G9 raport „nic” ma PDF', bool(r.get('nothing_erased')) and (kat / 'report.pdf').exists())
    sprawdz('SCHEMAT raport „nic” bez kluczy wewnętrznych', m.klucze_spoza_schematu(r) == [], str(m.klucze_spoza_schematu(r)[:10]))


if __name__ == '__main__':
    os.makedirs('/out-testy', exist_ok=True)
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sprawdz('harness bez wyjątku', False, str(e))
    finally:
        subprocess.run(['umount', MNT], capture_output=True)
        for dev in list(LOOPY):
            odlacz(dev)
    zle = [n for n, ok, _ in WYNIKI if not ok]
    print(f'\nWYNIK: {len(WYNIKI) - len(zle)}/{len(WYNIKI)} zielonych' + (f'; czerwone: {zle}' if zle else ''))
    json.dump([{'test': n, 'ok': ok, 'szczegol': s} for n, ok, s in WYNIKI], open('/out-testy/wyniki-urzadzenia.json', 'w'), ensure_ascii=False, indent=1)
    sys.exit(1 if zle else 0)
