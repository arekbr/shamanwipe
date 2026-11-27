"""Testy doboru metody i statusów — wyrocznią jest tabela decyzji (README, sekcja o doborze metody).

Uruchomienie:  SW_LANG=en python3 -I tests/test_dobor.py  i  SW_LANG=pl …  (dobór nie zależy od języka)      (SW_SRC=<plik> podmienia testowany program — używa tego tests/mutacje.sh)
Nic nie mutuje; czyste funkcje na danych z tests/fixtures/.
"""
import errno
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys
import time
import types
import unittest

TU = pathlib.Path(__file__).resolve().parent
SRC = os.environ.get('SW_SRC', str(TU.parent / 'src' / 'shamanwipe'))
_l = importlib.machinery.SourceFileLoader('sw', SRC)
_s = importlib.util.spec_from_loader('sw', _l)
sw = importlib.util.module_from_spec(_s)
_l.exec_module(sw)
FX = TU / 'fixtures'


def fx(nazwa):
    return (FX / nazwa).read_text()


def dysk_ata(plik, transport='sata', **dod):
    a = sw.parsuj_hdparm_I(fx(plik))
    assert a, plik
    a.setdefault('hpa', None)
    a.setdefault('dco_max', None)
    d = {'nazwa': 'sdx', 'sciezka': '/dev/sdx', 'transport': transport, 'interfejs': 'ata', 'ata': a, 'chroniony': [],
         'typ_nosnika': {True: 'SSD', False: 'HDD'}.get(a['ssd'], 'unknown'), 'model': a['model'], 'serial': a['serial'],
         'serial_zrodlo': 'ATA IDENTIFY', 'rozmiar_b': a['sektory'] * a['sektor_logiczny']}
    d.update(dod)
    return d


def dysk_nvme(sanicap=0, fna=0, oacs=2, liczba_ns=1):
    nv = sw.parsuj_nvme_id_ctrl({'mn': 'TEST NVME', 'sn': 'SN1', 'fr': '1', 'sanicap': sanicap, 'fna': fna, 'oacs': oacs})
    nv.update(kontroler='/dev/nvme0', liczba_ns=liczba_ns, ns={'lbaf': 0, 'ms': 0, 'pi': 0})
    return {'nazwa': 'nvme0n1', 'sciezka': '/dev/nvme0n1', 'transport': 'nvme', 'interfejs': 'nvme', 'nvme': nv,
            'typ_nosnika': 'NVMe SSD', 'chroniony': [], 'serial': 'SN1', 'serial_zrodlo': 'NVMe Identify', 'rozmiar_b': 10 ** 9}


class TabelaDecyzji(unittest.TestCase):
    def plan(self, d, profil='standard', **kw):
        return sw.wybierz_metode(d, profil, **kw)

    # --- SATA, prawdziwe dyski ---
    def test_crucial_bx500_sanitize_block(self):
        p = self.plan(dysk_ata('hdparm-crucial-bx500-0.txt'))
        self.assertEqual(p['kroki'], ['ata-sanitize-block'])
        self.assertEqual(p['klasa'], 'PURGE')
        self.assertEqual(p['zapasowe'][:2], ['ata-se-enhanced', 'ata-se-normal'])

    def test_samsung_pm871_enhanced_se_clear_z_adnotacja(self):
        p = self.plan(dysk_ata('hdparm-samsung-pm871-0.txt'))
        self.assertEqual(p['kroki'], ['ata-se-enhanced'])
        self.assertEqual(p['klasa'], 'CLEAR')
        self.assertTrue(any('IEEE 2883' in u for u in p['uwagi_metody']))

    def test_goodram_enhanced_se(self):
        p = self.plan(dysk_ata('hdparm-goodram-0.txt'))
        self.assertEqual(p['kroki'], ['ata-se-enhanced'])

    # --- SATA, syntetyczne ---
    def test_ssd_crypto_scramble_pierwszy(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-ssd-crypto.txt'))
        self.assertEqual(p['kroki'], ['ata-sanitize-crypto'])
        self.assertEqual(p['klasa'], 'PURGE')

    def test_ssd_frozen_wymaga_odmrozenia(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-ssd-frozen.txt'))
        self.assertEqual(p['kroki'], ['ata-se-enhanced'])
        self.assertIn('unfreeze', p['przygotowanie'])

    def test_zablokowany_haslem_bez_nadpisu(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-ssd-locked.txt'))
        self.assertFalse(p['mozliwe'])
        self.assertEqual(p['kroki'], [])

    def test_hdd_tylko_se(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-hdd-se.txt'))
        self.assertEqual(p['kroki'], ['ata-se-enhanced'])

    def test_hdd_sanitize_overwrite_bez_block(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-hdd-sanitize.txt'))
        self.assertEqual(p['kroki'], ['ata-sanitize-overwrite'])
        self.assertNotIn('ata-sanitize-block', p['kroki'] + p['zapasowe'])

    def test_hdd_bez_security_nadpis(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-hdd-bez-security.txt'))
        self.assertEqual(p['kroki'], ['overwrite-zeros'])
        self.assertEqual(p['klasa'], 'CLEAR')

    def test_hpa_wymaga_przywrocenia(self):
        d = dysk_ata('hdparm-samsung-pm871-0.txt')
        d['ata']['hpa'] = sw.parsuj_hdparm_N(' max sectors   = 400000000/500118192, HPA is enabled')
        self.assertIn('restore-max-lba', self.plan(d)['przygotowanie'])

    # --- NVMe ---
    def test_nvme_sanitize_crypto(self):
        p = self.plan(dysk_nvme(sanicap=7, fna=4))
        self.assertEqual(p['kroki'], ['nvme-sanitize-crypto'])
        self.assertEqual(p['klasa'], 'PURGE')
        self.assertEqual(p['zapasowe'], ['nvme-sanitize-block', 'nvme-sanitize-overwrite', 'nvme-format-crypto', 'nvme-format-user', 'overwrite-zeros'])

    def test_nvme_sanitize_block(self):
        self.assertEqual(self.plan(dysk_nvme(sanicap=2))['kroki'], ['nvme-sanitize-block'])

    def test_nvme_format_crypto_purge(self):
        p = self.plan(dysk_nvme(sanicap=0, fna=4))
        self.assertEqual(p['kroki'], ['nvme-format-crypto'])
        self.assertEqual(p['klasa'], 'PURGE')

    def test_nvme_format_user_clear(self):
        p = self.plan(dysk_nvme(sanicap=0, fna=0))
        self.assertEqual(p['kroki'], ['nvme-format-user'])
        self.assertEqual(p['klasa'], 'CLEAR')

    def test_nvme_wiele_ns_nie_wszystkie_wybrane(self):
        p = self.plan(dysk_nvme(sanicap=7, fna=1, liczba_ns=2))
        self.assertEqual(p['kroki'], ['overwrite-zeros'])

    def test_nvme_wiele_ns_wszystkie_wybrane(self):
        p = self.plan(dysk_nvme(sanicap=7, fna=1, liczba_ns=2), kontrolery_wspolne={'/dev/nvme0'})
        self.assertEqual(p['kroki'], ['nvme-sanitize-crypto'])

    # --- USB, RAID, chronione, profile ---
    def test_usb_bez_sat_klasa_brak(self):
        d = {'nazwa': 'sdu', 'sciezka': '/dev/sdu', 'transport': 'usb', 'interfejs': 'block', 'typ_nosnika': 'unknown', 'chroniony': []}
        p = self.plan(d)
        self.assertEqual(p['kroki'], ['overwrite-zeros'])
        self.assertEqual(p['klasa'], 'NONE')

    def test_raid_sprzetowy_recznie_brak_automat_pomija(self):
        d = {'nazwa': 'sda', 'sciezka': '/dev/sda', 'transport': 'sas', 'interfejs': 'block', 'typ_nosnika': 'HDD',
             'chroniony': [], 'raid_sprzetowy': True}
        self.assertEqual(self.plan(d)['klasa'], 'NONE')
        self.assertFalse(self.plan(d, automat=True)['mozliwe'])

    def test_chroniony(self):
        d = dysk_ata('hdparm-crucial-bx500-0.txt', chroniony=['nośnik startowy (live)'])
        self.assertFalse(self.plan(d)['mozliwe'])

    def test_profil_nadpis_i_max(self):
        d = dysk_ata('hdparm-crucial-bx500-0.txt')
        self.assertEqual(self.plan(d, 'overwrite')['kroki'], ['overwrite-zeros'])
        self.assertEqual(self.plan(d, 'nadpis')['kroki'], ['overwrite-zeros'])  # polski alias profilu
        self.assertEqual(self.plan(d, 'max')['kroki'], ['overwrite-random', 'ata-sanitize-block'])


class WarunkiSukcesu(unittest.TestCase):
    def test_sanitize_status_crucial_ok(self):
        self.assertEqual(sw.ocen_sanitize_status(fx('hdparm-sanitize-status-crucial-po.txt'))[0], 'OK')

    def test_sanitize_status_w_toku(self):
        t = 'Sanitize status:\n    State:    SD2 Sanitize operation In Process\n    Progress: 0x6400 (39%)\n'
        stan, post = sw.ocen_sanitize_status(t)
        self.assertEqual(stan, 'W_TOKU')
        self.assertAlmostEqual(post, 39.1, places=1)

    def test_se_ok(self):
        t = fx('hdparm-samsung-pm871-0.txt')
        self.assertEqual(sw.ocen_po_security_erase(0, t, 'TESTSN00000003')[0], 'OK')

    def test_se_goodram_brak_identify_niepotwierdzony(self):
        self.assertEqual(sw.ocen_po_security_erase(0, '', 'TESTSN002')[0], 'UNCONFIRMED')

    def test_se_inny_serial_blad(self):
        self.assertEqual(sw.ocen_po_security_erase(0, fx('hdparm-samsung-pm871-0.txt'), 'INNY')[0], 'BLAD')

    def test_se_haslo_zostalo_blad(self):
        self.assertEqual(sw.ocen_po_security_erase(0, fx('syntetyczny-hdparm-ssd-locked.txt'), 'TESTSN00000003')[0], 'BLAD')

    def test_se_rc_niezerowy_blad(self):
        self.assertEqual(sw.ocen_po_security_erase(5, fx('hdparm-samsung-pm871-0.txt'), 'TESTSN00000003')[0], 'BLAD')


class Z:
    def __init__(self, d, wynik='OK', niepotw=None):
        self.d, self.wynik, self.zastrzezenia, self.niepotwierdzone = d, wynik, [], list(niepotw or [])


class Statusy(unittest.TestCase):
    def d(self, typ='HDD', kroki=('overwrite-zeros',), smart=None, **dod):
        d = {'typ_nosnika': typ, 'interfejs': 'ata', 'transport': 'sata', 'serial_zrodlo': 'ATA IDENTIFY',
             'smart_przed': smart or {}, 'smart_po': smart or {}, 'plan': {'kroki': list(kroki)}}
        sw.uzupelnij_plan(d['plan'], d)
        d.update(dod)
        return d

    def test_skasowany(self):
        self.assertEqual(sw.ustal_status(Z(self.d(kroki=('ata-sanitize-block',), typ='SSD'))), 'ERASED')

    def test_hdd_48_reallocated_overwrite_warning(self):
        sm = sw.parsuj_smart(fx('smart-hdd-reallocated-48.json'))
        self.assertEqual(sm['realokowane'], 48)
        z = Z(self.d(smart=sm))
        self.assertEqual(sw.ustal_status(z), 'ERASED_WITH_WARNINGS')
        self.assertTrue(any(x.startswith('48 ') for x in z.zastrzezenia), z.zastrzezenia)  # liczba na początku w obu językach

    def test_ssd_tylko_nadpis_zastrzezenie(self):
        self.assertEqual(sw.ustal_status(Z(self.d(typ='SSD'))), 'ERASED_WITH_WARNINGS')

    def test_niepotwierdzony(self):
        self.assertEqual(sw.ustal_status(Z(self.d(), 'UNCONFIRMED', ['IDENTIFY po nie odpowiada'])), 'UNCONFIRMED')

    def test_rozmiar_niezgodny_niepotwierdzony(self):
        self.assertEqual(sw.ustal_status(Z(self.d(rozmiar_identify_b=1000, rozmiar_urzadzenia_b=900))), 'UNCONFIRMED')

    def test_niepowodzenie(self):
        self.assertEqual(sw.ustal_status(Z(self.d(), 'FAILED')), 'FAILED')

    def test_smart_wzrost_realokowanych(self):
        d = self.d(kroki=('ata-sanitize-block',), typ='SSD')
        d['smart_przed'], d['smart_po'] = {'realokowane': 0, 'zdrowie': True}, {'realokowane': 3, 'zdrowie': True}
        self.assertEqual(sw.ustal_status(Z(d)), 'ERASED_WITH_WARNINGS')


class Przebieg(unittest.TestCase):
    """Zadanie.wykonaj na atrapach (bez dysków): rezerwy po nieudanym przywróceniu HPA/DCO i hierarchia wyników."""

    def setUp(self):
        self.stare = {n: getattr(sw, n) for n in ('uruchom', 'log', 'smart_json')}
        sw.uruchom = lambda *a, **k: (0, '', '')
        sw.log = lambda *a, **k: None
        sw.smart_json = lambda *a, **k: ({}, '')

    def tearDown(self):
        for n, f in self.stare.items():
            setattr(sw, n, f)

    def zadanie(self, kroki, zapasowe, wyniki, przygotowanie=(), hpa_ok=True, weryfikacja=None, niepotw_po=()):
        """wyniki: {metoda: bool}; niepotw_po: metody, które po wykonaniu zgłaszają stan niepotwierdzony (rc=0)."""
        d = {'nazwa': 'sdx', 'sciezka': '/dev/sdx', 'typ_nosnika': 'SSD', 'interfejs': 'ata', 'transport': 'sata',
             'serial': 'S', 'serial_zrodlo': 'ATA IDENTIFY', 'rozmiar_b': 1 << 20, 'smart_przed': {}}
        d['plan'] = {'kroki': list(kroki), 'zapasowe': list(zapasowe), 'uwagi': [], 'przygotowanie': list(przygotowanie),
                     'mozliwe': True}
        sw.uzupelnij_plan(d['plan'], d)
        z = sw.Zadanie(d, 'standard')
        z.wykonane = []
        z._niszczace = lambda *a, **k: None
        z._koniec_operacji = lambda *a: None
        z._zapisz_znaczniki = lambda: ([{'pozycja': 0, 'sha256': 'x', 'jednolita': False}], True)
        z.przywroc_max_lba = lambda: hpa_ok

        def metoda(k):
            z.wykonane.append(k)
            if k in niepotw_po:
                z.niepotwierdzone.append('stan po operacji nieczytelny')
            return wyniki.get(k, False)
        z._wykonaj_metode = metoda
        dobra = {'zaliczona': True, 'zweryfikowane_b': 1 << 20}
        z.weryfikuj_zera = lambda: dict(weryfikacja or dobra)
        z.weryfikuj_znaczniki = lambda zn: dict(weryfikacja or dobra)
        z.wykonaj()
        return z

    def test_hpa_nieprzywrocone_bez_rezerwy_nadpisu(self):
        z = self.zadanie(['ata-se-enhanced'], ['ata-se-normal', 'overwrite-zeros'],
                         {'ata-se-enhanced': False, 'ata-se-normal': False, 'overwrite-zeros': True},
                         przygotowanie=['restore-max-lba'], hpa_ok=False)
        self.assertNotIn('overwrite-zeros', z.wykonane)  # nadpis nie obejmie ukrytego obszaru
        self.assertEqual(z.status, 'FAILED')

    def test_hpa_przywrocone_rezerwa_nadpisu_dziala(self):  # kontrola: ten sam układ z udanym HPA schodzi do nadpisu
        z = self.zadanie(['ata-se-enhanced'], ['ata-se-normal', 'overwrite-zeros'],
                         {'ata-se-enhanced': False, 'ata-se-normal': False, 'overwrite-zeros': True},
                         przygotowanie=['restore-max-lba'], hpa_ok=True)
        self.assertIn('overwrite-zeros', z.wykonane)
        self.assertEqual(z.status, 'ERASED_WITH_WARNINGS')

    def test_przetrwale_znaczniki_przy_stanie_niepotwierdzonym_to_failed(self):
        z = self.zadanie(['ata-sanitize-block'], ['overwrite-zeros'], {'ata-sanitize-block': True},
                         niepotw_po=('ata-sanitize-block',),
                         weryfikacja={'zaliczona': False, 'identyczne_jak_przed_niejednolite': 3, 'bledy_odczytu': 0})
        self.assertEqual(z.status, 'FAILED')

    def test_brak_odczytu_przy_stanie_niepotwierdzonym_to_unconfirmed(self):  # dysk po SE nie odpowiada: nie ma dowodu ani w jedną, ani w drugą stronę
        z = self.zadanie(['ata-se-enhanced'], ['overwrite-zeros'], {'ata-se-enhanced': True},
                         niepotw_po=('ata-se-enhanced',),
                         weryfikacja={'zaliczona': False, 'identyczne_jak_przed_niejednolite': 0, 'bledy_odczytu': 512})
        self.assertEqual(z.status, 'UNCONFIRMED')


class Odmrazanie(unittest.TestCase):
    """Dysk nadal zamrożony po uśpieniu: Security Erase znika z kroków ORAZ z rezerw (tabela: nadal frozen → nadpis)."""

    def setUp(self):
        self.stare = {n: getattr(sw, n) for n in ('uruchom', 'log', 'czytaj', 'odczytaj_tozsamosc', 'zgodna_tozsamosc')}
        sw.uruchom = lambda *a, **k: (1, '', '')  # hdparm -I po uśpieniu bez nowych danych → stan z IDENTIFY sprzed uśpienia
        sw.log = lambda *a, **k: None
        sw.czytaj = lambda *a, **k: ''  # brak S3: bez uśpienia
        sw.odczytaj_tozsamosc = lambda d: {}
        sw.zgodna_tozsamosc = lambda a, b: True

    def tearDown(self):
        for n, f in self.stare.items():
            setattr(sw, n, f)

    def test_nadal_zamrozony_bez_security_erase_w_krokach_i_rezerwach(self):
        d = dysk_ata('syntetyczny-hdparm-ssd-frozen.txt', tozsamosc={})
        d['plan'] = sw.wybierz_metode(d, 'standard')
        self.assertTrue(d['ata']['bezpieczenstwo'].get('zamrozone'))
        przed = d['plan']['kroki'] + d['plan']['zapasowe']
        self.assertTrue(any(k.startswith('ata-se') for k in przed), przed)  # kontrola: plan przed uśpieniem ma SE
        sw.odmroz_dyski([Z(d)])
        po = d['plan']['kroki'] + d['plan']['zapasowe']
        self.assertEqual([k for k in po if k.startswith('ata-se')], [], po)
        self.assertIn('overwrite-zeros', d['plan']['kroki'])

    def test_po_uspieniu_brak_flagi_frozen_zdejmuje_se_z_planu(self):  # nieznany stan = nadal zamrożony
        bez_flagi = '\n'.join(w for w in fx('syntetyczny-hdparm-ssd-frozen.txt').splitlines() if 'frozen' not in w)
        sw.uruchom = lambda cmd, **k: (0, bez_flagi, '') if cmd[:2] == ['hdparm', '-I'] else (1, '', '')
        d = dysk_ata('syntetyczny-hdparm-ssd-frozen.txt', tozsamosc={})
        d['plan'] = sw.wybierz_metode(d, 'standard')
        sw.odmroz_dyski([Z(d)])
        self.assertEqual([k for k in d['plan']['kroki'] + d['plan']['zapasowe'] if k.startswith('ata-se')], [])

    def _se(self, plik, ident=None, rc_ident=0):
        """ata_security_erase na atrapach; inwentarz z pliku, świeży hdparm -I = `ident` (domyślnie ten sam plik).
        Zwraca (wynik, wywołane polecenia)."""
        polecenia = []
        tekst = fx(plik) if ident is None else ident

        def uruchom(cmd, **k):
            polecenia.append(cmd)
            return (rc_ident, tekst, '') if cmd[:2] == ['hdparm', '-I'] else (0, '', '')
        sw.uruchom = uruchom
        d = dysk_ata(plik, tozsamosc={})
        z = sw.Zadanie(d, 'standard')
        z._niszczace = lambda *a, **k: None
        z._koniec_operacji = lambda *a: None
        try:
            wynik = z.ata_security_erase(enhanced=True)
        except Exception as e:  # dalsza część SE na atrapach może się wyłożyć — liczy się, czy padło polecenie hasła
            wynik = e
        return wynik, polecenia

    def test_se_jako_rezerwa_na_zamrozonym_dysku_nie_rusza(self):  # SE bywa rezerwą po Sanitize / w profilu nadpisu
        wynik, polecenia = self._se('syntetyczny-hdparm-ssd-frozen.txt')
        self.assertFalse([c for c in polecenia if '--security-set-pass' in c], polecenia)
        self.assertIs(wynik, False)

    def test_se_gdy_swiezy_identify_bez_flagi_frozen_nie_rusza(self):  # nieznany stan ≠ „not frozen”
        bez_flagi = '\n'.join(w for w in fx('syntetyczny-hdparm-ssd-frozen.txt').splitlines() if 'frozen' not in w)
        wynik, polecenia = self._se('syntetyczny-hdparm-ssd-frozen.txt', ident=bez_flagi)
        self.assertFalse([c for c in polecenia if '--security-set-pass' in c], polecenia)
        self.assertIs(wynik, False)

    def test_se_gdy_odczyt_identify_zawodzi_nie_rusza(self):  # nawet przy dysku „not frozen” w inwentarzu
        wynik, polecenia = self._se('hdparm-samsung-pm871-0.txt', rc_ident=1)
        self.assertFalse([c for c in polecenia if '--security-set-pass' in c], polecenia)
        self.assertIs(wynik, False)

    def test_se_na_odmrozonym_dysku_rusza(self):  # kontrola: ta sama ścieżka bez frozen ustawia hasło
        wynik, polecenia = self._se('hdparm-samsung-pm871-0.txt')
        self.assertTrue([c for c in polecenia if '--security-set-pass' in c], polecenia)


class Weryfikacja(unittest.TestCase):
    P = [{'pozycja': 0, 'sha256': 'a', 'jednolita': False}, {'pozycja': 4096, 'sha256': 'b', 'jednolita': False}]

    def test_znaczniki_przetrwaly(self):
        po = [{'pozycja': 0, 'sha256': 'a', 'jednolita': False}, {'pozycja': 4096, 'sha256': 'z', 'jednolita': True}]
        self.assertFalse(sw.ocen_probki(self.P, po)['zaliczona'])

    def test_znaczniki_zniknely(self):
        po = [{'pozycja': 0, 'sha256': 'z', 'jednolita': True}, {'pozycja': 4096, 'sha256': 'c', 'jednolita': False}]
        self.assertTrue(sw.ocen_probki(self.P, po)['zaliczona'])

    def test_blad_odczytu(self):
        po = [{'pozycja': 0, 'blad': 'EIO'}, {'pozycja': 4096, 'sha256': 'z', 'jednolita': True}]
        self.assertFalse(sw.ocen_probki(self.P, po)['zaliczona'])


class SprawdzoneNaSprzecie(unittest.TestCase):
    """Lista technik sprawdzonych na prawdziwym sprzęcie działa per technika, nie per rodzina."""

    def plan(self, d, profil='standard'):
        return sw.wybierz_metode(d, profil)

    def test_sanitize_block_sprawdzony_bez_adnotacji(self):
        p = self.plan(dysk_ata('hdparm-crucial-bx500-0.txt'))
        self.assertEqual(p['kroki'], ['ata-sanitize-block'])
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], [])

    def test_se_z_tej_samej_rodziny_nadal_niesprawdzony(self):
        p = self.plan(dysk_ata('hdparm-samsung-pm871-0.txt'))
        self.assertEqual(p['kroki'], ['ata-se-enhanced'])
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], ['ata-se-enhanced'])

    def test_sanitize_crypto_niesprawdzony(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-ssd-crypto.txt'))
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], ['ata-sanitize-crypto'])

    def test_nvme_niesprawdzony(self):
        p = self.plan(dysk_nvme(sanicap=7, fna=4))
        self.assertEqual(p['kroki'], ['nvme-sanitize-crypto'])
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], ['nvme-sanitize-crypto'])

    def test_rezerwa_se_po_sanitize_block_dostaje_adnotacje(self):
        d = dysk_ata('hdparm-crucial-bx500-0.txt')
        p = self.plan(d)
        p['kroki'][0] = 'ata-se-enhanced'  # tak przebieg zapisuje udaną rezerwę, potem przelicza plan
        sw.uzupelnij_plan(p, d)
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], ['ata-se-enhanced'])

    def test_nadpis_hosta_bez_adnotacji(self):
        p = self.plan(dysk_ata('syntetyczny-hdparm-hdd-bez-security.txt'))
        self.assertEqual(p['kroki'], ['overwrite-zeros'])
        self.assertEqual(p['niezweryfikowane_na_sprzecie'], [])

    def test_raport_wymienia_technike(self):
        d = dysk_ata('hdparm-samsung-pm871-0.txt')
        d['plan'] = self.plan(d)
        z = Z(d)
        z.komunikat = z.weryfikacja = z.zapisane_b = z.status = z.start = z.koniec = None
        z.kroki, z.dziennik_jadra = [], []
        uwagi = sw.wiersz_dysku(z)['uwagi']
        self.assertTrue([u for u in uwagi if u.endswith('(ata-se-enhanced)')], uwagi)


class UspienieDeep(unittest.TestCase):
    """Odmrażanie: tryb deep (S3) wybierany na czas uśpienia, gdy jądro go oferuje; poprzedni tryb zawsze wraca."""

    def setUp(self):
        self.stare = {n: getattr(sw, n) for n in ('uruchom', 'log', 'czytaj', 'zapisz_sysfs', 'odczytaj_tozsamosc',
                                                  'zgodna_tozsamosc', 'time')}
        self.state, self.mem_sleep, self.zapis_ok, self.rtc_wyjatek, self.ident = 'freeze mem', '[s2idle] deep', True, False, None
        self.rtc_rc, self.log_wyjatek = 0, False
        self.zdarzenia = []
        sw.czytaj = lambda p, *a, **k: {'/sys/power/state': self.state, '/sys/power/mem_sleep': self.mem_sleep}.get(p, '')
        sw.zapisz_sysfs = lambda p, t: (self.zdarzenia.append(('zapis', p, t)), self.zapis_ok)[1]

        def log(tekst, *a, **k):
            if self.log_wyjatek and '-> deep' in tekst:
                raise RuntimeError('log po przełączeniu')
        sw.log = log
        sw.odczytaj_tozsamosc = lambda d: {}
        sw.zgodna_tozsamosc = lambda a, b: True
        sw.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)

        def uruchom(cmd, **k):
            if cmd[0] == 'rtcwake':
                self.zdarzenia.append(('rtcwake',))
                if self.rtc_wyjatek:
                    raise RuntimeError('rtcwake')
                return self.rtc_rc, '', ''
            if cmd[:2] == ['hdparm', '-I'] and self.ident:
                return 0, self.ident, ''
            return 1, '', ''
        sw.uruchom = uruchom
        self.d = dysk_ata('syntetyczny-hdparm-ssd-frozen.txt', tozsamosc={})
        self.d['plan'] = sw.wybierz_metode(self.d, 'standard')
        self.assertIn('unfreeze', self.d['plan']['przygotowanie'])  # kontrola: ten dysk naprawdę wymaga odmrożenia

    def tearDown(self):
        for n, f in self.stare.items():
            setattr(sw, n, f)

    ZAPIS = ('zapis', '/sys/power/mem_sleep')

    def test_s2idle_przelacza_na_deep_i_przywraca(self):
        sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [self.ZAPIS + ('deep',), ('rtcwake',), self.ZAPIS + ('s2idle',)])
        self.assertEqual(self.d['plan']['odmrozenie_tryb'], 'deep')
        self.assertIn('deep', self.d['plan']['odmrozenie_wynik'])

    def test_bez_deep_bez_zapisu(self):
        self.mem_sleep = '[s2idle]'
        sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [('rtcwake',)])
        self.assertEqual(self.d['plan']['odmrozenie_tryb'], 's2idle')

    def test_deep_juz_wybrany_bez_zapisu(self):
        self.mem_sleep = 's2idle [deep]'
        sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [('rtcwake',)])
        self.assertEqual(self.d['plan']['odmrozenie_tryb'], 'deep')

    def test_nieudany_zapis_uspienie_w_biezacym_trybie(self):
        self.zapis_ok = False
        sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [self.ZAPIS + ('deep',), ('rtcwake',)])  # nic do przywracania
        self.assertEqual(self.d['plan']['odmrozenie_tryb'], 's2idle')

    def test_blad_rtcwake_tryb_i_tak_przywrocony(self):
        self.rtc_wyjatek = True
        with self.assertRaises(RuntimeError):
            sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia[-1], self.ZAPIS + ('s2idle',))

    def test_wyjatek_tuz_po_przelaczeniu_tryb_wraca(self):  # try/finally obejmuje już sam zapis „deep”
        self.log_wyjatek = True
        with self.assertRaises(RuntimeError):
            sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [self.ZAPIS + ('deep',), self.ZAPIS + ('s2idle',)])

    def test_rtcwake_niezerowy_kod_w_raporcie(self):  # 124 = timeout: uśpienia mogło nie być — raport to mówi
        self.rtc_rc = 124
        sw.odmroz_dyski([Z(self.d)])
        self.assertIn('rtcwake rc=124', self.d['plan']['odmrozenie_wynik'])
        self.rtc_rc = 0
        self.d['plan'] = sw.wybierz_metode(self.d, 'standard')
        sw.odmroz_dyski([Z(self.d)])
        self.assertNotIn('rtcwake rc', self.d['plan']['odmrozenie_wynik'])

    def test_brak_uspienia_w_jadrze(self):
        self.state = 'freeze'
        sw.odmroz_dyski([Z(self.d)])
        self.assertEqual(self.zdarzenia, [])
        self.assertIsNone(self.d['plan']['odmrozenie_tryb'])
        self.assertIn(sw.L('brak', 'none'), self.d['plan']['odmrozenie_wynik'])

    def test_odmrozony_po_deep_zostawia_security_erase(self):
        self.ident = fx('hdparm-samsung-pm871-0.txt')  # świeży IDENTIFY: not frozen
        sw.odmroz_dyski([Z(self.d)])
        self.assertTrue(self.d['plan']['odmrozenie_wynik'].startswith(sw.L('odmrożony', 'unfrozen')))
        self.assertTrue(any(k.startswith('ata-se') for k in self.d['plan']['kroki'] + self.d['plan']['zapasowe']))


class PelnyOdczytBledy(unittest.TestCase):
    """Pełny odczyt: błąd odczytu zostawia offset, długość, errno i kod; do raportu idzie wycinek dmesg o tym urządzeniu."""
    B = sw.ROZMIAR_BLOKU_IO
    DMESG = '\n'.join([
        '[   12.3] sd 2:0:0:0: [sdc] tag#0 FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_OK',
        '[   12.4] I/O error, dev sdc, sector 16384 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 2',
        '[   12.5] usb 2-1: reset high-speed USB device number 3 using xhci_hcd',
        '[   12.6] I/O error, dev sdb, sector 8 op 0x0:(READ)',
        '[   12.7] EXT4-fs (sdc1): mounted filesystem'])

    def setUp(self):
        self.stare = {n: getattr(sw, n) for n in ('UrzadzenieBlokowe', 'uruchom', 'log')}
        self.polecenia = []
        test = self

        class Falszywe:
            def __init__(self, sciezka):
                self.rozmiar = test.bloki * test.B

            def czytaj(self, buf, poz, dl):
                if poz // test.B in test.zle:
                    raise OSError(errno.EIO, 'Input/output error')
                buf[:dl] = bytes(dl)
                return dl

            def zamknij(self):
                pass
        sw.UrzadzenieBlokowe = Falszywe
        sw.uruchom = lambda cmd, **k: (self.polecenia.append(cmd), (0, self.DMESG, ''))[1]
        sw.log = lambda *a, **k: None
        self.z = sw.Zadanie({'sciezka': '/dev/sdc', 'nazwa': 'sdc'}, 'standard')

    def tearDown(self):
        for n, f in self.stare.items():
            setattr(sw, n, f)

    def test_offset_errno_i_dziennik_jadra(self):
        self.bloki, self.zle = 10, {2, 7}
        w = self.z.weryfikuj_zera()
        self.assertFalse(w['zaliczona'])
        self.assertEqual(w['bledy_odczytu'], 2)
        self.assertEqual(w['bledy_odczytu_szczegoly'],
                         [{'offset': 2 * self.B, 'dlugosc': self.B, 'errno': errno.EIO, 'kod': 'EIO'},
                          {'offset': 7 * self.B, 'dlugosc': self.B, 'errno': errno.EIO, 'kod': 'EIO'}])
        self.assertEqual(self.z.dziennik_jadra, self.DMESG.splitlines()[:2])  # tylko sdc, bez sdb i sdc1
        self.assertEqual(w['zweryfikowane_b'], 8 * self.B)  # 2 bloki z błędem nie są zweryfikowane

    def test_wyjatek_dmesg_nie_gubi_szczegolow(self):  # np. PermissionError przy uruchamianiu procesu
        def uruchom(cmd, **k):
            raise PermissionError(errno.EPERM, 'dmesg')
        sw.uruchom = uruchom
        self.bloki, self.zle = 4, {1}
        w = self.z.weryfikuj_zera()
        self.assertEqual([s['offset'] for s in w['bledy_odczytu_szczegoly']], [self.B])
        self.assertEqual(self.z.dziennik_jadra, [])

    def test_pelny_run_log_nie_gubi_szczegolow(self):  # ENOSPC przy dopisywaniu linii jądra do run.log
        def log(tekst, *a, **k):
            if 'kernel:' in tekst:
                raise OSError(errno.ENOSPC, 'No space left on device')
        sw.log = log
        self.bloki, self.zle = 3, {0}
        w = self.z.weryfikuj_zera()
        self.assertEqual([s['kod'] for s in w['bledy_odczytu_szczegoly']], ['EIO'])
        self.assertEqual(len(self.z.dziennik_jadra), 2)

    def test_nvme_takze_komunikaty_kontrolera(self):
        sw.uruchom = lambda cmd, **k: (0, '\n'.join(['[ 1.0] nvme nvme0: I/O 7 QID 2 timeout, reset controller',
                                                    '[ 1.1] I/O error, dev nvme0n1, sector 0 op 0x0:(READ)',
                                                    '[ 1.2] nvme nvme1: I/O 9 QID 1 timeout',
                                                    '[ 1.3] nvme0n1p1: something']), '')
        self.z = sw.Zadanie({'sciezka': '/dev/nvme0n1', 'nazwa': 'nvme0n1'}, 'standard')
        self.bloki, self.zle = 2, {0}
        self.z.weryfikuj_zera()
        self.assertEqual([w[:6] for w in self.z.dziennik_jadra], ['[ 1.0]', '[ 1.1]'])

    def test_limit_szczegolow_liczba_laczna_pelna(self):
        self.bloki, self.zle = 20, set(range(20))
        w = self.z.weryfikuj_zera()
        self.assertEqual(w['bledy_odczytu'], 20)
        self.assertEqual(len(w['bledy_odczytu_szczegoly']), sw.MAKS_BLEDOW_ODCZYTU_W_RAPORCIE)

    def test_bez_bledow_bez_dmesg(self):
        self.bloki, self.zle = 3, set()
        w = self.z.weryfikuj_zera()
        self.assertTrue(w['zaliczona'])
        self.assertEqual((w['bledy_odczytu_szczegoly'], self.z.dziennik_jadra, self.polecenia), ([], [], []))

    def test_klucze_eksportu_po_angielsku(self):
        r = sw.raport_eksport({'dziennik_jadra': ['x'], 'weryfikacja': {'bledy_odczytu_szczegoly': [
            {'offset': 1, 'dlugosc': 2, 'errno': 5, 'kod': 'EIO'}]}})
        self.assertEqual(r, {'kernel_log': ['x'], 'verification': {'read_error_details': [
            {'offset': 1, 'length': 2, 'errno': 5, 'code': 'EIO'}]}})
        self.assertEqual(sw.klucze_spoza_schematu(r), [])  # kontrola schematu przyjmuje nowe klucze


class Drobne(unittest.TestCase):
    def test_potwierdzenie(self):
        self.assertTrue(sw.potwierdzenie_poprawne('kasuj 2', 2))
        self.assertFalse(sw.potwierdzenie_poprawne('KASUJ', 2))
        self.assertFalse(sw.potwierdzenie_poprawne('KASUJ 3', 2))

    def test_parametry_jadra(self):
        self.assertEqual(sw.parametry_jadra('boot=live sw.auto=standard sw.after=poweroff sw.lang=pl quiet'), {'auto': 'standard', 'after': 'poweroff', 'lang': 'pl'})

    def test_hdparm_nie_ata(self):
        self.assertIsNone(sw.parsuj_hdparm_I('SG_IO: bad/missing sense data'))

    def test_nvme_id_ns_rozmiar(self):
        ns = sw.parsuj_nvme_id_ns({'nsze': 1000, 'flbas': 1, 'dps': 0, 'lbafs': [{'ds': 9}, {'ds': 12}]})
        self.assertEqual((ns['lbaf'], ns['rozmiar_b']), (1, 1000 * 4096))


if __name__ == '__main__':
    unittest.main(verbosity=1)
