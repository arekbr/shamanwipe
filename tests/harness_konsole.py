"""Konsole i blokada — WEWNĄTRZ kontenera amd64, przez tests/test_urzadzenia.sh (interfejs polski: SW_LANG=pl).

R1  dwie instancje `start` (tryb ręczny) → OBIE pokazują menu.
R2  AUTOMAT na A (tty1), podgląd na B (ttyS0): KAŻDY klawisz na B (Enter, Ctrl+C, litera, Esc, spacja) → A: PRZERWANE,
    cel nietknięty, B: werdykt potwierdzony przez A. R2w: klawisz bez Entera na samym A. R2b: bajt w buforze B przed startem.
R3  blokada trzymana przez A (kasuj) → `kasuj` z B odrzucone; mutacja bez flocka musi to wywrócić (falsyfikator).
R4  pierwszeństwo: B=tty1 startuje PO A=ttyS0, a AUTOMAT bierze B; po przerwaniu ttyS0 NIE startuje AUTOMATU od nowa;
    przejęcie przez ttyS0 tylko bez instancji tty1.
R5  menu B przy cudzej blokadzie: inwentarz → podgląd, „Wyłącz komputer” → odmowa.
R6  G13: operacja z żywym PID-em tego rozruchu = W TOKU, nie „niedokończona”.
R7  haki SW_* bez SW_TEST_TYLKO_LOOP=1 są ignorowane (odliczanie, parametry jądra, katalogi).
R8  interfejs angielski: menu z sw.lang=en (parametr jądra), AUTOMAT po angielsku przerwany z drugiej konsoli.
Mutuje wyłącznie własne obrazy w /work i podłączone przez siebie loopy (SW_TEST_TYLKO_LOOP=1). Procesy na pty zabija
całymi grupami w finally.
"""
import fcntl
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

_l = importlib.machinery.SourceFileLoader('harness', '/src/tests/harness_urzadzenia.py')
h = importlib.util.module_from_spec(importlib.util.spec_from_loader('harness', _l))
_l.exec_module(h)
SRC, W = h.SRC, h.W
ENV = dict(h.ENV, TERM='linux', LANG='C.UTF-8')
RUN = ENV['SW_RUN']
ANSI = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>78]|\x0f|\x0e')
PROCESY = []


class Konsola:
    def __init__(self, nazwa, env, przed=b'', program=SRC, args=('start',)):
        self.nazwa, self.bufor = nazwa, b''
        self.m, s = os.openpty()
        fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 160, 0, 0))
        if przed:  # bajty „naciśnięte” zanim program wystartował (leżą w buforze terminala)
            os.write(self.m, przed)
        # pty jako terminal sterujący (jak konsola z getty): Ctrl+C przy włączonym ISIG daje SIGINT grupie procesów
        self.p = subprocess.Popen([sys.executable, '-I', program, *args], stdin=s, stdout=s, stderr=s, env=env,
                                  start_new_session=True, close_fds=True,
                                  preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        os.close(s)
        PROCESY.append(self)

    def tekst(self):
        return ANSI.sub(b'', self.bufor).replace(b'\r', b'').decode('utf-8', 'replace')

    def _czytaj(self, limit):
        r, _, _ = select.select([self.m], [], [], limit)
        if r:
            try:
                self.bufor += os.read(self.m, 65536)
            except OSError:
                return False
        return True

    def czekaj(self, wzorzec, limit):
        koniec = time.time() + limit
        while time.time() < koniec:
            if re.search(wzorzec, self.tekst()):
                return True
            if not self._czytaj(0.3):
                break
        return bool(re.search(wzorzec, self.tekst()))

    def czekaj_koniec(self, limit):
        koniec = time.time() + limit
        while time.time() < koniec and self.p.poll() is None:
            self._czytaj(0.3)
        self._czytaj(0.2)
        return self.p.poll()

    def wyslij(self, t):
        os.write(self.m, t.encode() if isinstance(t, str) else t)

    def zabij(self):
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, signal.SIGTERM)
                self.p.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            os.close(self.m)
        except OSError:
            pass


def env(konsola, **dod):
    return dict(ENV, SW_KONSOLA=konsola, **dod)


def nowy_rozruch():
    """Między scenariuszami: stan AUTOMATU jak po świeżym rozruchu (/run jest tmpfs)."""
    for p in [os.path.join(RUN, 'automat.json')] + glob.glob(os.path.join(RUN, 'przerwij-*')) + glob.glob(os.path.join(RUN, 'instancja-*')):
        try:
            os.remove(p)
        except OSError:
            pass


def ogon(k, n=300):
    return k.tekst()[-n:].replace('\n', ' | ')


def r1():
    e = dict(SW_TEST_CMDLINE='sw.test=reczny')
    a = Konsola('A', env('/dev/tty1', **e))
    ok_a = a.czekaj(r'Wybierz działanie', 40)
    b = Konsola('B', env('/dev/ttyS0', **e))
    ok_b = b.czekaj(r'Wybierz działanie|innej konsoli', 40)
    h.sprawdz('R1 konsola A: menu', ok_a, ogon(a))
    h.sprawdz('R1 konsola B: też menu (nie sam podgląd)', ok_b and 'Wybierz działanie' in b.tekst(), ogon(b))
    a.zabij()
    b.zabij()


def automat_a(odliczanie='15', konsola='/dev/tty1', **dod):
    nowy_rozruch()
    a = Konsola('A', env(konsola, SW_TEST_CMDLINE='sw.auto=overwrite', SW_ODLICZANIE=odliczanie, **dod))
    return a, a.czekaj(r'start za', 90)


def r2(cel, sha_cel):
    for nazwa, klawisz in (('Enter', '\r'), ('Ctrl+C', '\x03'), ('litera bez Entera', 'x'), ('Esc', '\x1b'), ('spacja', ' ')):
        a, odl = automat_a()
        b = Konsola('B', env('/dev/ttyS0', SW_TEST_CMDLINE='sw.auto=overwrite'))
        pod = b.czekaj(r'Podgląd przebiegu', 30)
        time.sleep(1.5)
        b.wyslij(klawisz)
        a.czekaj(r'PRZERWANE|AUTO DONE', 60)
        b.czekaj(r'PRZERWANO — potwierdzone|ZA PÓŹNO', 20)
        h.sprawdz(f'R2 [{nazwa}] na konsoli B przerywa AUTOMAT na A', odl and pod and 'PRZERWANE' in a.tekst(), ogon(a))
        h.sprawdz(f'R2 [{nazwa}] cel nietknięty (SHA-256)', h.sha(cel) == sha_cel)
        h.sprawdz(f'R2 [{nazwa}] B pokazuje werdykt potwierdzony przez A', 'PRZERWANO — potwierdzone' in b.tekst(), ogon(b))
        a.zabij()
        b.zabij()
    # R2w: klawisz bez Entera na konsoli samego AUTOMATU (dawniej wymagał Entera)
    a, odl = automat_a()
    time.sleep(1)
    a.wyslij('q')
    a.czekaj(r'PRZERWANE|AUTO DONE', 30)
    h.sprawdz('R2w litera bez Entera na konsoli AUTOMATU przerywa', odl and 'PRZERWANE' in a.tekst(), ogon(a))
    h.sprawdz('R2w cel nietknięty', h.sha(cel) == sha_cel)
    a.zabij()
    # R2b: bajt w buforze konsoli B, zanim program B wystartował (operator naciskał w trakcie rozruchu)
    a, odl = automat_a()
    b = Konsola('B', env('/dev/ttyS0', SW_TEST_CMDLINE='sw.auto=overwrite'), przed=b'k')
    a.czekaj(r'PRZERWANE|AUTO DONE', 60)
    h.sprawdz('R2b bajt sprzed startu podglądu przerywa AUTOMAT', odl and 'PRZERWANE' in a.tekst(), ogon(a))
    h.sprawdz('R2b cel nietknięty', h.sha(cel) == sha_cel)
    a.zabij()
    b.zabij()


def r3():
    c1, c2 = h.obraz('r3-c1.img', 16), h.obraz('r3-c2.img', 16)
    d1, d2 = h.podlacz(c1), h.podlacz(c2)
    sha2 = h.sha(c2)
    flaga = W / 'r3-go'
    a = Konsola('A', env('/dev/tty1', SW_TEST_PODMIANA=str(flaga)), args=('kasuj', '--dysk', d1, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1'))
    trzyma = a.czekaj(r'SWAP: waiting', 60)
    b = subprocess.run([sys.executable, '-I', SRC, 'kasuj', '--dysk', d2, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1'],
                       capture_output=True, text=True, env=env('/dev/ttyS0'), timeout=120)
    h.sprawdz('R3 druga operacja przy cudzej blokadzie: odmowa (rc 3)', trzyma and b.returncode == 3 and 'ODMOWA' in b.stdout,
              f'rc={b.returncode} {b.stdout[-200:]}')
    h.sprawdz('R3 drugi cel nietknięty', h.sha(c2) == sha2)
    # Falsyfikator: ta sama próba programem bez flocka MUSI skasować drugi cel (inaczej R3 nie umie być czerwony)
    mut = W / 'sw-no-flock'
    zrodlo = open(SRC, encoding='utf-8').read()
    wzor = '        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n        return f\n'
    mut.write_text(zrodlo.replace(wzor, '        return f\n', 1), encoding='utf-8')
    bm = subprocess.run([sys.executable, '-I', str(mut), 'kasuj', '--dysk', d2, '--profil', 'nadpis', '--potwierdzam', 'KASUJ 1'],
                        capture_output=True, text=True, env=env('/dev/ttyS0'), timeout=300)
    h.sprawdz('R3 falsyfikator: mutacja bez flocka kasuje mimo blokady (test umie być czerwony)',
              wzor in zrodlo and bm.returncode == 0 and h.same_zera(c2), f'rc={bm.returncode}')
    flaga.touch()
    a.czekaj_koniec(120)
    a.zabij()
    h.odlacz(d1)
    h.odlacz(d2)


def r4(cel, sha_cel):
    # B (tty1) startuje 2 s PO A (ttyS0) — AUTOMAT ma wziąć B
    nowy_rozruch()
    e = dict(SW_TEST_CMDLINE='sw.auto=overwrite', SW_ODLICZANIE='15')
    a = Konsola('A', env('/dev/ttyS0', **e))
    time.sleep(2)
    b = Konsola('B', env('/dev/tty1', **e))
    b_odl = b.czekaj(r'start za', 90)
    a_pod = a.czekaj(r'Podgląd przebiegu', 30)
    h.sprawdz('R4 pierwszeństwo tty1: AUTOMAT na tty1, ttyS0 w podglądzie', b_odl and a_pod and 'start za' not in a.tekst(),
              f'A: {ogon(a, 150)} || B: {ogon(b, 150)}')
    time.sleep(1)
    a.wyslij('z')
    b.czekaj(r'PRZERWANE|AUTO DONE', 60)
    h.sprawdz('R4 klawisz na ttyS0 przerywa AUTOMAT na tty1', 'PRZERWANE' in b.tekst(), ogon(b))
    b.czekaj_koniec(20)
    a.czekaj_koniec(30)
    # Po przerwaniu: nowa instancja na ttyS0 NIE może zacząć AUTOMATU od nowa
    c = Konsola('C', env('/dev/ttyS0', SW_TEST_PRZEJECIE_S='2', **e))
    rc = c.czekaj_koniec(40)
    h.sprawdz('R4 po przerwaniu ttyS0 nie startuje AUTOMATU ponownie', rc is not None and 'start za' not in c.tekst(), ogon(c))
    h.sprawdz('R4 cel nietknięty', h.sha(cel) == sha_cel)
    for k in (a, b, c):
        k.zabij()
    # Przejęcie: brak instancji tty1, AUTOMAT w tym rozruchu nie ruszał → ttyS0 przejmuje po SW_TEST_PRZEJECIE_S
    nowy_rozruch()
    d = Konsola('D', env('/dev/ttyS0', SW_TEST_PRZEJECIE_S='3', **e))
    przejal = d.czekaj(r'start za', 60)
    time.sleep(1)
    d.wyslij('n')
    d.czekaj(r'PRZERWANE|AUTO DONE', 30)
    h.sprawdz('R4 bez instancji tty1: ttyS0 przejmuje AUTOMAT (i daje się przerwać)', przejal and 'Brak programu na konsoli /dev/tty1' in d.tekst()
              and 'PRZERWANE' in d.tekst(), ogon(d))
    h.sprawdz('R4 cel nietknięty po przejęciu', h.sha(cel) == sha_cel)
    d.zabij()


def r5(cel, sha_cel):
    a, odl = automat_a(odliczanie='45')
    b = Konsola('B', env('/dev/tty2', SW_TEST_CMDLINE='sw.test=reczny'))
    menu = b.czekaj(r'Wybierz działanie', 40)
    time.sleep(1.5)
    b.wyslij('\x1b[B')
    time.sleep(0.5)
    b.wyslij('\r')  # 2 = Inwentarz
    pod = b.czekaj(r'Operacja na dyskach trwa na innej konsoli', 20)
    h.sprawdz('R5 inwentarz na B przy cudzej blokadzie → podgląd (bez poleceń do dysków)', odl and menu and pod, ogon(b))
    time.sleep(1)
    b.wyslij('\x03')  # Ctrl+C: z podglądu ręcznego z powrotem do menu
    b.bufor = b''
    wrocil = b.czekaj(r'Wybierz działanie', 20)
    time.sleep(1.5)
    for _ in range(5):
        b.wyslij('\x1b[B')
        time.sleep(0.4)
    b.wyslij('\r')  # 6 = Wyłącz komputer
    odm = b.czekaj(r'NIE wyłączam komputera', 20)
    h.sprawdz('R5 „Wyłącz komputer” na B przy cudzej blokadzie → odmowa', wrocil and odm, ogon(b))
    a.wyslij('q')
    a.czekaj(r'PRZERWANE|AUTO DONE', 30)
    h.sprawdz('R5 cel nietknięty', 'PRZERWANE' in a.tekst() and h.sha(cel) == sha_cel, ogon(a))
    a.zabij()
    b.zabij()


def r6():
    m = h.modul()
    plik = m.plik_dziennika()
    biez = m.boot_id()
    with open(plik, 'a') as f:
        for w in ({'id': 'R6-zywy', 'state': 'start', 'boot_id': biez, 'pid': os.getpid(), 'time': 'x'},
                  {'id': 'R6-martwy', 'state': 'start', 'boot_id': biez, 'pid': 4194000, 'time': 'x'},
                  {'id': 'R6-inny-rozruch', 'state': 'start', 'boot_id': 'inny', 'pid': os.getpid(), 'time': 'x'}):
            f.write(json.dumps(w) + '\n')
    ids = {w['id'] for w in m.niedokonczone_operacje()}
    h.sprawdz('R6 operacja z żywym PID-em tego rozruchu = W TOKU (nie na liście)', 'R6-zywy' not in ids, str(ids))
    h.sprawdz('R6 martwy PID i inny rozruch = niedokończone', {'R6-martwy', 'R6-inny-rozruch'} <= ids, str(ids))
    with open(plik, 'a') as f:
        for i in ('R6-zywy', 'R6-martwy', 'R6-inny-rozruch'):
            f.write(json.dumps({'id': i, 'state': 'end'}) + '\n')


def r8(cel, sha_cel):
    """Interfejs angielski: język z parametru jądra (bez SW_LANG) i AUTOMAT po angielsku przerwany z konsoli B."""
    bez_lang = {k: v for k, v in ENV.items() if k != 'SW_LANG'}
    for jezyk, wzor in (('en', 'Choose an action'), ('pl', 'Wybierz działanie')):
        a = Konsola('A', dict(bez_lang, SW_KONSOLA='/dev/tty1', SW_TEST_CMDLINE=f'sw.lang={jezyk} sw.test=reczny'))
        h.sprawdz(f'R8 sw.lang={jezyk} w linii jądra → menu „{wzor}”', a.czekaj(wzor, 40), ogon(a))
        a.zabij()
    nowy_rozruch()
    a = Konsola('A', env('/dev/tty1', SW_LANG='en', SW_TEST_CMDLINE='sw.auto=overwrite', SW_ODLICZANIE='15'))
    odl = a.czekaj(r'starting in', 90)
    b = Konsola('B', env('/dev/ttyS0', SW_LANG='en', SW_TEST_CMDLINE='sw.auto=overwrite'))
    pod = b.czekaj(r'Progress view', 30)
    time.sleep(1.5)
    b.wyslij('\r')
    a.czekaj(r'ABORTED|AUTO DONE', 60)
    b.czekaj(r'ABORTED — confirmed|TOO LATE', 20)
    h.sprawdz('R8 EN: AUTOMAT po angielsku, Enter na B przerywa (A: ABORTED)', odl and pod and 'ABORTED — nothing was erased' in a.tekst(), ogon(a))
    h.sprawdz('R8 EN: B pokazuje werdykt potwierdzony przez A', 'ABORTED — confirmed by the AUTO console' in b.tekst(), ogon(b))
    h.sprawdz('R8 EN: cel nietknięty', h.sha(cel) == sha_cel)
    a.zabij()
    b.zabij()


def r7():
    kod = ('import importlib.machinery as M, importlib.util as U;'
           f'l=M.SourceFileLoader("j","{SRC}");m=U.module_from_spec(U.spec_from_loader("j",l));l.exec_module(m);'
           'print(m.ODLICZANIE_AUTOMAT_S, "auto" in m.parametry_jadra(), m.KATALOG_RUN, m.MNT_RAPORTY, m.TRYB_TESTOWY)')
    czyste = {k: v for k, v in os.environ.items() if not k.startswith('SW_')}
    p = subprocess.run([sys.executable, '-I', '-c', kod], capture_output=True, text=True,
                       env=dict(czyste, SW_ODLICZANIE='0', SW_TEST_CMDLINE='sw.auto=standard', SW_RUN='/tmp/x', SW_MNT_RAPORTY='/tmp/y'))
    h.sprawdz('R7 haki SW_* bez trybu testowego ignorowane', p.stdout.split() == ['60', 'False', '/run/shamanwipe', '/mnt/sw-reports', 'False'],
              p.stdout + p.stderr[-200:])


if __name__ == '__main__':
    W.mkdir(exist_ok=True)
    for i in range(64):
        if not os.path.exists(f'/dev/loop{i}'):
            subprocess.run(['mknod', f'/dev/loop{i}', 'b', '7', str(i)])
    try:
        r7()
        r1()
        h.przygotuj_raporty()  # SW-REPORTS z kluczem testowym bez hasła — AUTOMAT nie pyta o hasło
        iso = h.obraz('k-nosnik.img', 32, losowy=False)
        h.sh('mkfs.vfat', '-n', 'SHAMANWIPE', h.podlacz(iso))
        cel = h.obraz('k-cel.img', 32)
        h.podlacz(cel)
        sha_cel = h.sha(cel)
        r2(cel, sha_cel)
        r4(cel, sha_cel)
        r5(cel, sha_cel)
        r6()
        r8(cel, sha_cel)
        r3()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        h.sprawdz('harness konsol bez wyjątku', False, str(e))
    finally:
        for k in PROCESY:
            k.zabij()
        subprocess.run(['umount', h.MNT], capture_output=True)
        for dev in list(h.LOOPY):
            h.odlacz(dev)
    zle = [n for n, ok, _ in h.WYNIKI if not ok]
    print(f'\nWYNIK KONSOLE: {len(h.WYNIKI) - len(zle)}/{len(h.WYNIKI)} zielonych' + (f'; czerwone: {zle}' if zle else ''))
    sys.exit(1 if zle else 0)
