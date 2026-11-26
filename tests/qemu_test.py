#!/usr/bin/env python3
"""Testy ISO shamanwipe w QEMU (G2, G3, G4, G5, G9) — uruchamiane na macOS przez tests/qemu-test.sh.

Języki: domyślna pozycja menu (G2, G3) = angielski tryb ręczny; G9a = polski AUTOMAT (ISOLINUX), G9b = angielski (GRUB).

Start WYŁĄCZNIE przez bootloader ISO (bez -kernel), wybór pozycji menu klawiszami na konsoli szeregowej. Konsola
ttyS0 przez socket AF_UNIX; tty1 (konsola lokalna) sterowana przez QMP send-key. Log każdego scenariusza:
tests/wyniki/qemu/<scenariusz>.log; wynik zbiorczy: tests/wyniki/qemu/wyniki.json. Każdy QEMU zabijany w finally.
Mutuje wyłącznie pliki w tests/wyniki/qemu/obrazy (kopie pendrive'a, dyski celów); ISO i obraz wzorcowy — tylko odczyt.
"""
import hashlib
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import time

KAT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WYN = os.path.join(KAT, 'tests', 'wyniki', 'qemu')
OBR = os.path.join(WYN, 'obrazy')
QEMU = shutil.which('qemu-system-x86_64') or '/opt/homebrew/bin/qemu-system-x86_64'
SHARE = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(QEMU))), 'share', 'qemu')
OVMF_KOD = os.path.join(SHARE, 'edk2-x86_64-code.fd')
OVMF_ZMIENNE = os.path.join(SHARE, 'edk2-i386-vars.fd')  # magazyn zmiennych jest niezależny od architektury
OPENSSL = '/opt/homebrew/bin/openssl'  # /usr/bin/openssl na macOS = LibreSSL bez Ed25519
ANSI = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>78]|\x0f|\x0e')
MB = 1024 * 1024
WYNIKI = []
STRZALKA_W_DOL = '\x1b[B'


def czysc(b):
    return ANSI.sub(b'', b).replace(b'\r', b'').decode('utf-8', 'replace')


def sprawdz(nazwa, warunek, szczegol=''):
    WYNIKI.append({'test': nazwa, 'ok': bool(warunek), 'szczegol': str(szczegol)[-600:]})
    print(('OK   ' if warunek else 'BŁĄD ') + nazwa + (f'  [{str(szczegol)[-300:]}]' if szczegol and not warunek else ''), flush=True)


def sha(p, ile=None):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        zostalo = ile
        while True:
            k = f.read(MB if zostalo is None else min(MB, zostalo))
            if not k:
                break
            h.update(k)
            if zostalo is not None:
                zostalo -= len(k)
                if zostalo <= 0:
                    break
    return h.hexdigest()


def same_zera(p):
    z = bytes(MB)
    with open(p, 'rb') as f:
        for k in iter(lambda: f.read(MB), b''):
            if k != z[:len(k)]:
                return False
    return True


def obraz_losowy(nazwa, mb):
    p = os.path.join(OBR, nazwa)
    with open(p, 'wb') as f:
        for _ in range(mb):
            f.write(os.urandom(MB))
    return p


class Konsola:
    """Minimalny „expect” na konsoli szeregowej QEMU."""

    def __init__(self, sciezka_sock, plik_logu, limit_polaczenia=30):
        self.log = open(plik_logu, 'ab')
        self.bufor = b''
        t0 = time.time()
        while True:
            self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self.s.connect(sciezka_sock)
                break
            except OSError:
                self.s.close()
                if time.time() - t0 > limit_polaczenia:
                    raise
                time.sleep(0.2)

    def _czytaj(self, limit):
        r, _, _ = select.select([self.s], [], [], limit)
        if not r:
            return False
        dane = self.s.recv(65536)
        if not dane:
            raise EOFError('konsola zamknięta (QEMU zakończył pracę)')
        self.log.write(dane)
        self.log.flush()
        self.bufor += dane
        return True

    def czekaj(self, wzorce, limit):
        """Pierwszy z wzorców (regex na tekście bez ANSI). (indeks, dopasowanie) albo (-1, None). Bufor po dopasowaniu
        zawiera tylko tekst za nim."""
        koniec = time.time() + limit
        wz = [re.compile(w) for w in wzorce]
        while True:
            tekst = czysc(self.bufor)
            for i, w in enumerate(wz):
                m = w.search(tekst)
                if m:
                    self.bufor = tekst[m.end():].encode('utf-8', 'replace')
                    return i, m
            zostalo = koniec - time.time()
            if zostalo <= 0:
                return -1, None
            try:
                self._czytaj(min(zostalo, 1.0))
            except EOFError:
                return -1, None

    def wyslij(self, tekst):
        self.s.sendall(tekst.encode('utf-8') if isinstance(tekst, str) else tekst)

    def klawisze(self, *sekw, odstep=0.6):
        for s in sekw:
            self.wyslij(s)
            time.sleep(odstep)

    def polecenie(self, cmd, limit=120):
        """Polecenie w powłoce; (rc, wyjście). Znacznik zawiera liczbę wyliczaną przez powłokę — echo polecenia
        nie daje fałszywego dopasowania."""
        znak = f'Q{int(time.time() * 1000) % 100000}'
        self.wyslij(f'{cmd}; echo "{znak}-RC=$((40+2))-$?"\r')
        i, m = self.czekaj([rf'([\s\S]*?){znak}-RC=42-(\d+)'], limit)
        if i < 0:
            return None, czysc(self.bufor)[-2000:]
        linie = m.group(1).split('\n')
        linie = [l for l in linie if f'{znak}-RC=' not in l and not l.startswith('root@shamanwipe')]
        return int(m.group(2)), '\n'.join(linie).strip()

    def zamknij(self):
        try:
            self.s.close()
        finally:
            self.log.close()


QCODE = {'-': 'minus', ' ': 'spc', '\n': 'ret', '.': 'dot', '_': ('shift', 'minus'), '/': 'slash'}


class QMP:
    """Klawiatura konsoli lokalnej (tty1) przez QMP send-key."""

    def __init__(self, sciezka, limit=30):
        t0 = time.time()
        while True:
            self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self.s.connect(sciezka)
                break
            except OSError:
                self.s.close()
                if time.time() - t0 > limit:
                    raise
                time.sleep(0.2)
        self.f = self.s.makefile('rwb')
        self.f.readline()
        self.cmd('qmp_capabilities')

    def cmd(self, execute, **args):
        self.f.write(json.dumps({'execute': execute, 'arguments': args} if args else {'execute': execute}).encode() + b'\n')
        self.f.flush()
        while True:
            odp = json.loads(self.f.readline())
            if 'return' in odp or 'error' in odp:
                return odp

    def pisz(self, tekst):
        for ch in tekst:
            if ch.isalpha() and ch.isupper():
                kody = ('shift', ch.lower())
            elif ch.isalnum():
                kody = (ch,)
            else:
                q = QCODE[ch]
                kody = q if isinstance(q, tuple) else (q,)
            self.cmd('send-key', keys=[{'type': 'qcode', 'data': k} for k in kody])
            time.sleep(0.08)

    def zamknij(self):
        try:
            self.s.close()
        except OSError:
            pass


class Maszyna:
    def __init__(self, nazwa, tryb, nosnik, plik, dyski=(), tylko_odczyt=False, pamiec=2048):
        """tryb: bios|uefi; nosnik: cdrom|usb; plik: ISO albo obraz pendrive'a; dyski: [(plik, transport, serial)]."""
        self.nazwa, self.tryb = nazwa, tryb
        os.makedirs(WYN, exist_ok=True)
        self.log = os.path.join(WYN, f'{nazwa}.log')
        if os.path.exists(self.log):
            os.remove(self.log)
        self.sock = f'/tmp/swq-{os.getpid()}-{nazwa}.sock'
        self.qmp_sock = f'/tmp/swq-{os.getpid()}-{nazwa}.qmp'
        for g in (self.sock, self.qmp_sock):
            if os.path.exists(g):
                os.remove(g)
        cmd = [QEMU, '-machine', 'q35', '-accel', 'tcg,thread=multi', '-cpu', 'max', '-smp', '4', '-m', str(pamiec),
               '-display', 'none', '-no-reboot',
               '-chardev', f'socket,id=s0,path={self.sock},server=on,wait=off', '-serial', 'chardev:s0',
               '-qmp', f'unix:{self.qmp_sock},server=on,wait=off', '-nic', 'none']
        if tryb == 'uefi':
            zm = os.path.join(WYN, f'{nazwa}-ovmf-vars.fd')
            shutil.copy(OVMF_ZMIENNE, zm)
            cmd += ['-drive', f'if=pflash,format=raw,unit=0,readonly=on,file={OVMF_KOD}',
                    '-drive', f'if=pflash,format=raw,unit=1,file={zm}']
        cmd += ['-device', 'qemu-xhci,id=xhci']
        if nosnik == 'cdrom':
            cmd += ['-drive', f'if=none,id=boot,media=cdrom,readonly=on,format=raw,file={plik}',
                    '-device', 'ide-cd,drive=boot,bus=ide.2,bootindex=0']
        else:
            cmd += ['-drive', f'if=none,id=boot,format=raw,file={plik}' + (',snapshot=on' if tylko_odczyt else ''),
                    '-device', 'usb-storage,bus=xhci.0,drive=boot,serial=SWBOOT0001,bootindex=0']
        scsi = False
        for i, (p, transport, sn) in enumerate(dyski):
            cmd += ['-drive', f'if=none,id=d{i},format=raw,file={p}']
            if transport == 'nvme':
                cmd += ['-device', f'nvme,drive=d{i},serial={sn}']
            elif transport == 'sata':
                cmd += ['-device', f'ide-hd,drive=d{i},bus=ide.{i % 2},serial={sn}']  # q35: ide.0–ide.5 = AHCI
            elif transport == 'scsi':
                if not scsi:
                    cmd += ['-device', 'virtio-scsi-pci,id=vscsi']
                    scsi = True
                cmd += ['-device', f'scsi-hd,drive=d{i},bus=vscsi.0,serial={sn}']
            elif transport == 'usb':
                cmd += ['-device', f'usb-storage,bus=xhci.0,drive=d{i},serial={sn}']
        self.cmd, self.proc, self.k, self.qmp = cmd, None, None, None

    def start(self):
        with open(os.path.join(WYN, f'{self.nazwa}.cmd'), 'w') as f:
            f.write(' '.join(self.cmd) + '\n')
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL,
                                     stderr=open(os.path.join(WYN, f'{self.nazwa}.stderr'), 'w'))
        self.k = Konsola(self.sock, self.log)
        self.qmp = QMP(self.qmp_sock)
        return self.k

    def wylacz(self, limit=120):
        """sync + poweroff z powłoki na konsoli szeregowej; czeka na koniec QEMU (zapis obrazów na dysk hosta)."""
        if self.k and self.proc.poll() is None:
            try:
                self.k.wyslij('\rsync; poweroff\r')
            except OSError:
                pass
            try:
                self.proc.wait(limit)
            except subprocess.TimeoutExpired:
                pass
        return self.proc.poll() is not None

    def stop(self):
        for x in (self.k, self.qmp):
            if x:
                try:
                    x.zamknij()
                except OSError:
                    pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        for g in (self.sock, self.qmp_sock):
            if os.path.exists(g):
                os.remove(g)


def do_powloki(k, limit=600, jezyk='en'):
    """Z menu programu na konsoli szeregowej do powłoki root: strzałki do „5 Powłoka” (whiptail na konsoli szeregowej
    nie przeskakuje po znaku etykiety), Enter."""
    i, _ = k.czekaj([r'Choose an action' if jezyk == 'en' else r'Wybierz działanie'], limit)
    if i < 0:
        return False
    time.sleep(3)
    k.klawisze(*([STRZALKA_W_DOL] * 4), '\r', odstep=0.5)
    j, _ = k.czekaj([r'Root shell' if jezyk == 'en' else r'Powłoka root'], 60)
    time.sleep(1)
    k.wyslij('\r')
    return j == 0


def wybierz_automat(k, tryb, jezyk):
    """Pozycja AUTO standard w menu bootloadera (ISOLINUX dla BIOS, GRUB dla UEFI): 4 pozycje (EN/PL ręczny, EN/PL
    inwentarz) w dół, Enter (podmenu AUTO: Wróć, EN standard, EN + wyłącz, PL standard, PL + wyłącz), w dół, Enter."""
    # tytuł ISOLINUX jest na konsoli szeregowej ucinany po prawej — czekamy na jego początek
    tytul = r'ShamanWipe - secure disk erasure' if tryb == 'bios' else r'GNU GRUB'
    i, _ = k.czekaj([tytul], 180)
    if i < 0:
        return False
    time.sleep(1.5)
    k.klawisze(*([STRZALKA_W_DOL] * 4), '\r', odstep=0.8)
    time.sleep(1.5)
    k.klawisze(*([STRZALKA_W_DOL] * (1 if jezyk == 'en' else 3)), '\r', odstep=0.8)
    return True


def etykiety_menu(bl=os.path.join(KAT, 'lb', 'config', 'bootloaders')):
    """Napisy menu z konfiguracji bootloaderów: {(tryb, 'glowne'|'auto'): [...]}. ISOLINUX: tytuł z menu.cfg, etykiety
    z live.cfg.in (etykieta bloku „menu begin” należy do menu głównego). GRUB na konsoli szeregowej pokazuje każdy
    znak spoza ASCII jako „?”."""
    e = {(t, c): [] for t in ('bios', 'uefi') for c in ('glowne', 'auto')}
    with open(os.path.join(bl, 'syslinux_common', 'menu.cfg')) as f:
        e[('bios', 'glowne')] += [s[11:].strip() for s in f if s.startswith('menu title ')]
    blok, w_pozycji = False, False
    with open(os.path.join(bl, 'syslinux_common', 'live.cfg.in')) as f:
        for s in (x.strip() for x in f):
            if s.startswith('menu begin'):
                blok, w_pozycji = True, False
            elif s == 'menu end':
                blok = False
            elif s.startswith('label '):
                w_pozycji = blok
            elif (m := re.match(r'menu (label|title) (.*)', s)) and not (not blok and m.group(1) == 'title'):
                glowne = not blok or (m.group(1) == 'label' and not w_pozycji)
                e[('bios', 'glowne' if glowne else 'auto')].append(m.group(2).replace('^', ''))
    w_auto = False
    with open(os.path.join(bl, 'grub-pc', 'grub.cfg')) as f:
        for s in f:
            if s.startswith('}'):
                w_auto = False
            if not (m := re.match(r'(\t*)(menuentry|submenu) "([^"]*)"', s)):
                continue
            napis = re.sub(r'[^\x00-\x7f]', '?', m.group(3))
            if not m.group(1):
                e[('uefi', 'glowne')].append(napis)
                w_auto = m.group(2) == 'submenu' and m.group(3).startswith('AUTO')
            elif w_auto:
                e[('uefi', 'auto')].append(napis)
    return e


def menu_uciete(plik_logu, napisy):
    """Napisy menu, których nie ma w logu konsoli w całości (ucięte ramką ISOLINUX albo krawędzią ekranu GRUB)."""
    with open(plik_logu, 'rb') as f:
        tekst = czysc(f.read())
    return [n for n in napisy if n not in tekst]


def lista_dyskow(k):
    rc, wyj = k.polecenie("shamanwipe lista --json | jq -c '[.[]|{n:.nazwa,t:.transport,s:.serial,z:.serial_zrodlo,"
                          "c:.chroniony,p:.plan.technika,k:.plan.klasa}]'", 300)
    try:
        return json.loads(wyj.strip().split('\n')[-1])
    except (ValueError, IndexError):
        return None


def g2(iso, pendrive):
    """4 rozruchy przez bootloader: BIOS/UEFI × cdrom/USB; baner zgodny z trybem; domyślnie tryb ręczny."""
    for tryb in ('bios', 'uefi'):
        for nosnik, plik in (('cdrom', iso), ('usb', pendrive)):
            m = Maszyna(f'g2-{tryb}-{nosnik}', tryb, nosnik, plik, tylko_odczyt=True)
            t0 = time.time()
            try:
                k = m.start()
                i, mm = k.czekaj([r'BOOT=(BIOS|UEFI) · reports: ([^\n]*)'], 600)
                baner = mm.group(1) if mm else None
                powloka = do_powloki(k)
                rc, cmdline = k.polecenie('cat /proc/cmdline')
                rc2, efi = k.polecenie('[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS')
                sprawdz(f'G2 {tryb}/{nosnik}: baner BOOT={baner} zgodny z trybem', baner == tryb.upper() and efi.strip().endswith(tryb.upper()),
                        f'baner={baner} efi={efi}')
                sprawdz(f'G2 {tryb}/{nosnik}: domyślnie tryb ręczny po angielsku (menu, sw.lang=en, brak sw.auto)', powloka and rc == 0
                        and 'sw.auto' not in cmdline and 'sw.lang=en' in cmdline and 'boot=live' in cmdline, cmdline)
                u = menu_uciete(m.log, etykiety_menu()[(tryb, 'glowne')])
                sprawdz(f'G2 {tryb}/{nosnik}: menu główne bootloadera bez uciętych pozycji', not u, '; '.join(u))
                if nosnik == 'usb':
                    sprawdz(f'G2 {tryb}/usb: SW-REPORTS z pendrive\'a zamontowane', mm and 'SW-REPORTS' in mm.group(2), mm.group(2) if mm else '')
                print(f'   ({m.nazwa}: {time.time() - t0:.0f} s)', flush=True)
                m.wylacz()
            finally:
                m.stop()


def g3_g4_kasuj(pendrive, haslo):
    """Rozruch z pendrive'a (UEFI) z dyskami nvme/sata/scsi/usb: G3 (nośnik CHRONIONY z S/N, transporty), G4 (kasuj
    jednego dysku nadpisem; pozostałe = dyski kontrolne bez zmian; ISO na pendrivie bez zmian), G5 (podpis)."""
    kopia = os.path.join(OBR, 'g3-pendrive.img')
    shutil.copyfile(pendrive, kopia)
    start_rap = obszar_iso(kopia)
    sha_iso = sha(kopia, start_rap)
    dyski = [(obraz_losowy('g3-nvme.img', 64), 'nvme', 'SWNVME0001'), (obraz_losowy('g3-sata.img', 64), 'sata', 'SWSATA0001'),
             (obraz_losowy('g3-scsi.img', 64), 'scsi', 'SWSCSI0001'), (obraz_losowy('g3-usb.img', 64), 'usb', 'SWUSBD0001')]
    przed = {d[2]: sha(d[0]) for d in dyski}
    m = Maszyna('g3-uefi-usb', 'uefi', 'usb', kopia, dyski=dyski)
    kat = None
    try:
        k = m.start()
        k.czekaj([r'BOOT=UEFI'], 600)
        do_powloki(k)
        lista = lista_dyskow(k) or []
        po_sn = {d.get('s'): d for d in lista}
        boot = po_sn.get('SWBOOT0001', {})
        sprawdz('G3 nośnik startowy (USB, S/N SWBOOT0001) CHRONIONY jako nośnik startowy',
                any('boot medium' in c for c in boot.get('c') or []), json.dumps(boot, ensure_ascii=False))
        for sn, tr in (('SWNVME0001', 'nvme'), ('SWSATA0001', 'sata'), ('SWUSBD0001', 'usb')):
            d = po_sn.get(sn, {})
            sprawdz(f'G3 transport {tr}: wykryty, S/N {sn}, nie chroniony', d.get('t') == tr and not d.get('c'), json.dumps(d, ensure_ascii=False))
        d = po_sn.get('SWSCSI0001', {})
        sprawdz('G3 virtio-scsi: dysk wykryty z S/N, nie chroniony', bool(d) and not d.get('c'), json.dumps(d, ensure_ascii=False))
        with open(os.path.join(WYN, 'g3-lista.json'), 'w') as f:
            json.dump(lista, f, ensure_ascii=False, indent=1)
        sata = po_sn.get('SWSATA0001', {}).get('n')
        # kasuj z podpisem: hasło klucza na konsoli szeregowej (bez echa)
        znak = 'K' + str(int(time.time()) % 100000)
        k.wyslij(f'shamanwipe erase --disk /dev/{sata} --profile overwrite --confirm "ERASE 1"; echo "{znak}-RC=$((40+2))-$?"\r')
        i, _ = k.czekaj([r'Report signing key passphrase'], 300)
        if i == 0:
            time.sleep(1)
            k.wyslij(haslo + '\r')
        i, mm = k.czekaj([rf'{znak}-RC=42-(\d+)'], 900)
        rc = int(mm.group(1)) if mm else None
        sprawdz('G4 erase (nadpis) dysku SATA w QEMU: rc=0', rc == 0, czysc(k.bufor)[-400:])
        rc, kat = k.polecenie('ls -1d /mnt/sw-reports/reports/2* | tail -1')
        rc, wer = k.polecenie(f'shamanwipe verify {kat}')
        sprawdz('G5 raport z QEMU: shamanwipe verify = VALID (w systemie live)', rc == 0 and 'VALID' in wer, wer)
        m.wylacz()
    finally:
        m.stop()
    po = {d[2]: sha(d[0]) for d in dyski}
    sprawdz('G4 cel SATA: każdy bajt = 0', same_zera(dyski[1][0]))
    sprawdz('G4 dyski kontrolne (nvme, scsi, usb) bez zmian (SHA-256)', all(po[sn] == przed[sn] for sn in ('SWNVME0001', 'SWSCSI0001', 'SWUSBD0001')))
    sprawdz('G4 pendrive: obszar ISO bez zmian (zmienia się tylko SW-REPORTS)', sha(kopia, start_rap) == sha_iso)
    if kat:
        weryfikuj_na_maku(kopia, os.path.basename(kat.strip()), 'G5 kasuj')
    for d in dyski:
        os.remove(d[0])


def obszar_iso(img):
    """Bajt początku partycji 3 (SW-REPORTS) z MBR obrazu pendrive'a."""
    with open(img, 'rb') as f:
        f.seek(446 + 2 * 16 + 8)
        return int.from_bytes(f.read(4), 'little') * 512


def weryfikuj_na_maku(img, kat_raportu, etykieta):
    """Partycja SW-REPORTS z obrazu podłączona na macOS (MBR po unieważnieniu APM/GPT) — weryfikacja raportu OpenSSL 3+."""
    out = subprocess.run(['diskutil', 'image', 'attach', '--readOnly', '--noMount', img], capture_output=True, text=True).stdout
    dysk = (re.findall(r'^(/dev/disk\d+)\s', out, re.M) or [None])[0]
    if not dysk:
        sprawdz(f'{etykieta}: obraz podłączony na macOS', False, out)
        return
    try:
        mp = os.path.join(OBR, 'mnt-sw-reports')
        os.makedirs(mp, exist_ok=True)
        r = subprocess.run(['diskutil', 'mount', 'readOnly', '-mountPoint', mp, dysk + 's3'], capture_output=True, text=True)
        kat = os.path.join(mp, 'reports', kat_raportu)
        ok_kat = r.returncode == 0 and os.path.isdir(kat)
        sprawdz(f'{etykieta}: SW-REPORTS z obrazu widoczna i zamontowana na macOS', ok_kat, r.stdout + r.stderr)
        if ok_kat:
            p = subprocess.run([OPENSSL, 'pkeyutl', '-verify', '-pubin', '-inkey', os.path.join(kat, 'public-key.pem'), '-rawin',
                                '-in', os.path.join(kat, 'MANIFEST.sha256'), '-sigfile', os.path.join(kat, 'MANIFEST.sha256.sig')],
                               capture_output=True, text=True)
            s = subprocess.run(['shasum', '-a', '256', '-c', 'MANIFEST.sha256'], cwd=kat, capture_output=True, text=True)
            sprawdz(f'{etykieta}: podpis Ed25519 WAŻNY w {OPENSSL} na macOS + sumy zgodne', 'Signature Verified Successfully' in p.stdout
                    and s.returncode == 0, p.stdout + p.stderr + s.stdout[-200:])
            dst = os.path.join(WYN, f'raport-{etykieta.replace(" ", "-")}')
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(kat, dst)
        subprocess.run(['diskutil', 'unmount', mp], capture_output=True)
    finally:
        subprocess.run(['diskutil', 'eject', dysk], capture_output=True)


def g9_przerwanie(pendrive):
    """AUTOMAT (BIOS, USB) wybrany w ISOLINUX; konsola szeregowa = podgląd; klawisz na niej przerywa; cele bez zmian."""
    kopia = os.path.join(OBR, 'g9a-pendrive.img')
    shutil.copyfile(pendrive, kopia)
    dyski = [(obraz_losowy('g9a-sata.img', 32), 'sata', 'SWSATA0002'), (obraz_losowy('g9a-nvme.img', 32), 'nvme', 'SWNVME0002')]
    przed = [sha(d[0]) for d in dyski]
    m = Maszyna('g9-przerwanie-bios-usb', 'bios', 'usb', kopia, dyski=dyski)
    try:
        k = m.start()
        wyb = wybierz_automat(k, 'bios', 'pl')
        i, _ = k.czekaj([r'Command line: [^\n]*sw\.lang=pl[^\n]*sw\.auto=standard'], 300)
        sprawdz('G9 polski AUTOMAT wybrany w menu ISOLINUX (sw.lang=pl, sw.auto=standard w linii jądra)', wyb and i == 0)
        u = menu_uciete(m.log, etykiety_menu()[('bios', 'auto')])
        sprawdz('G9 podmenu AUTO w ISOLINUX bez uciętych pozycji', not u, '; '.join(u))
        i, _ = k.czekaj([r'Podgląd przebiegu'], 600)
        sprawdz('G9 konsola szeregowa: podgląd (AUTOMAT na konsoli lokalnej tty1 — pierwszeństwo)', i == 0)
        i, _ = k.czekaj([r'faza hasło|kasowanie za'], 600)
        time.sleep(2)
        k.wyslij('x')
        j, _ = k.czekaj([r'PRZERWANO — potwierdzone'], 180)
        sprawdz('G9 klawisz na konsoli szeregowej przerywa AUTOMAT (potwierdzone przez tty1)', i >= 0 and j == 0, czysc(k.bufor)[-400:])
        k.czekaj([r'root@shamanwipe'], 120)
        rc, aj = k.polecenie('cat /run/shamanwipe/automat.json')
        sprawdz('G9 faza AUTOMATU = przerwany', '"faza": "przerwany"' in aj, aj[-300:])
        m.wylacz()
    finally:
        m.stop()
    sprawdz('G9 po przerwaniu cele bez zmian (SHA-256)', [sha(d[0]) for d in dyski] == przed)
    for d in dyski:
        os.remove(d[0])
    os.remove(kopia)


def g9_pelny(pendrive, haslo):
    """AUTOMAT (UEFI, USB) wybrany w GRUB; hasło klucza wpisane na tty1 przez QMP; 60 s odliczania; kasowanie; raport
    podpisany; cele skasowane; obszar ISO pendrive'a bez zmian; weryfikacja raportu na macOS."""
    kopia = os.path.join(OBR, 'g9b-pendrive.img')
    shutil.copyfile(pendrive, kopia)
    start_rap = obszar_iso(kopia)
    sha_iso = sha(kopia, start_rap)
    # NVMe 64 MiB > 512 × 64 KiB próbek: odróżnia „zweryfikowane = rozmiar” (nadpis) od próbkowania znacznikami
    dyski = [(obraz_losowy('g9b-sata.img', 32), 'sata', 'SWSATA0003'), (obraz_losowy('g9b-nvme.img', 64), 'nvme', 'SWNVME0003')]
    przed = [sha(d[0]) for d in dyski]
    m = Maszyna('g9-pelny-uefi-usb', 'uefi', 'usb', kopia, dyski=dyski)
    raport = None
    try:
        k = m.start()
        wyb = wybierz_automat(k, 'uefi', 'en')
        i, _ = k.czekaj([r'Command line: [^\n]*sw\.lang=en[^\n]*sw\.auto=standard'], 300)
        sprawdz('G9 angielski AUTO wybrany w menu GRUB (sw.lang=en, sw.auto=standard w linii jądra)', wyb and i == 0)
        u = menu_uciete(m.log, etykiety_menu()[('uefi', 'auto')])
        sprawdz('G9 podmenu AUTO w GRUB bez uciętych pozycji', not u, '; '.join(u))
        i, _ = k.czekaj([r'phase key passphrase'], 900)
        time.sleep(3)
        m.qmp.pisz(haslo + '\n')
        j, _ = k.czekaj([r'erasure in'], 120)
        sprawdz('G9 po haśle na tty1: odliczanie widoczne w podglądzie konsoli szeregowej', i == 0 and j == 0)
        t_odl = time.time()
        i, mm = k.czekaj([r'Results: ([^\n]*)'], 1800)
        sprawdz('G9 AUTOMAT zakończony, wyniki w podglądzie', i == 0, czysc(k.bufor)[-400:])
        print(f'   (od odliczania do końca: {time.time() - t_odl:.0f} s; wyniki: {mm.group(1) if mm else "-"})', flush=True)
        k.czekaj([r'root@shamanwipe'], 120)
        rc, aj = k.polecenie('cat /run/shamanwipe/automat.json')
        try:
            a = json.loads(aj.strip().split('\n')[-1])
        except ValueError:
            a = {}
        raport = a.get('raport')
        rc, wer = k.polecenie(f'shamanwipe verify {raport}')
        sprawdz('G5 raport AUTOMATU: verify = VALID (podpisany hasłem z tty1)', rc == 0 and 'VALID' in wer, wer)
        rc, js = k.polecenie(f"jq -c '[.disks[]|{{u:.device,s:.serial_number,t:.technique,st:.status,z:.bytes_verified,"
                             f"r:.device_size_bytes,m:.verification.method,mt:.media_type}}]' {raport}/report.json")
        try:
            dy = json.loads(js.strip().split('\n')[-1])
        except ValueError:
            dy = []
        po_sn = {d.get('s'): d for d in dy}
        s_, n_ = po_sn.get('SWSATA0003', {}), po_sn.get('SWNVME0003', {})
        # status wg tabeli decyzji: nadpis HDD bez zastrzeżeń SMART = ERASED, nadpis SSD = ERASED_WITH_WARNINGS
        st_ok = {'HDD': 'ERASED', 'SSD': 'ERASED_WITH_WARNINGS'}.get(s_.get('mt'))
        sprawdz('G4 raport: SATA nadpis — technika podana, status zgodny z typem nośnika, zweryfikowane = rozmiar (pełny odczyt)',
                s_.get('t', '').startswith('Single-pass zero overwrite') and st_ok is not None and s_.get('st') == st_ok
                and s_.get('z') == s_.get('r') == 32 * MB, json.dumps(s_, ensure_ascii=False))
        sprawdz('G4 raport: NVMe — technika firmware podana, zweryfikowane = 512 × 64 KiB próbek < rozmiar (bez zawyżania)',
                n_.get('t', '').startswith('NVMe') and 'markers' in (n_.get('m') or '') and n_.get('z') == 512 * 65536 < (n_.get('r') or 0),
                json.dumps(n_, ensure_ascii=False))
        with open(os.path.join(WYN, 'g9-pelny-dyski.json'), 'w') as f:
            json.dump(dy, f, ensure_ascii=False, indent=1)
        m.wylacz()
    finally:
        m.stop()
    po = [sha(d[0]) for d in dyski]
    sprawdz('G4 AUTOMAT: oba cele zmienione (SHA-256 ≠ przed)', all(a != b for a, b in zip(po, przed)))
    sprawdz('G4 AUTOMAT: cel SATA (nadpis) — każdy bajt = 0', same_zera(dyski[0][0]))
    sprawdz('G4 AUTOMAT: obszar ISO na pendrivie bez zmian', sha(kopia, start_rap) == sha_iso)
    if raport:
        weryfikuj_na_maku(kopia, os.path.basename(raport), 'G5 AUTOMAT')
    for d in dyski:
        os.remove(d[0])


if __name__ == '__main__':
    polecenie = sys.argv[1]
    iso = os.path.join(KAT, 'out', f'shamanwipe-{open(os.path.join(KAT, "VERSION")).read().strip()}-amd64.iso')
    pendrive = os.path.join(OBR, f'shamanwipe-{open(os.path.join(KAT, "VERSION")).read().strip()}-pendrive.img')
    haslo = open(os.path.join(OBR, 'haslo-testowe.txt')).read().strip() if os.path.exists(os.path.join(OBR, 'haslo-testowe.txt')) else ''
    scen = {'g2': lambda: g2(iso, pendrive), 'g3': lambda: g3_g4_kasuj(pendrive, haslo), 'g9a': lambda: g9_przerwanie(pendrive),
            'g9b': lambda: g9_pelny(pendrive, haslo)}
    wybrane = list(scen) if polecenie == 'wszystko' else polecenie.split(',')
    for s in wybrane:
        try:
            scen[s]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            sprawdz(f'{s}: scenariusz bez wyjątku', False, repr(e))
    zle = [w['test'] for w in WYNIKI if not w['ok']]
    with open(os.path.join(WYN, f'wyniki-{polecenie.replace(",", "-")}.json'), 'w') as f:
        json.dump(WYNIKI, f, ensure_ascii=False, indent=1)
    print(f'\nWYNIK QEMU ({polecenie}): {len(WYNIKI) - len(zle)}/{len(WYNIKI)} zielonych' + (f'; czerwone: {zle}' if zle else ''))
    sys.exit(1 if zle else 0)
