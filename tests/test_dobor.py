"""Testy doboru metody i statusów — wyrocznią jest tabela decyzji (README, sekcja o doborze metody).

Uruchomienie:  SW_LANG=en python3 -I tests/test_dobor.py  i  SW_LANG=pl …  (dobór nie zależy od języka)      (SW_SRC=<plik> podmienia testowany program — używa tego tests/mutacje.sh)
Nic nie mutuje; czyste funkcje na danych z tests/fixtures/.
"""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys
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
