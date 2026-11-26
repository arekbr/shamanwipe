<p align="center"><img src="assets/logo-tile.png" width="200" alt="Szamani Krzemu"></p>

# ShamanWipe

**Startowy system Debian 13 live do bezpiecznego kasowania dysków** — sprzętowe kasowanie SSD/NVMe tam, gdzie dysk
je obsługuje, nadpis z weryfikacją tam, gdzie nie, i podpisany raport (PDF, JSON, CSV, XML) z każdego kasowania.

Polski · [English](README.md)

> Stan: **0.1.0, wczesne wydanie.** Cały przebieg jest przetestowany w kontenerach i w QEMU (BIOS i UEFI, płyta
> i USB). Polecenia kasowania w firmware są tak dobre, jak firmware dysku, i nie dla każdej klasy urządzeń zostały
> już potwierdzone przez ShamanWipe na prawdziwym sprzęcie — do tego czasu każdy raport mówi to wprost
> („technika niezweryfikowana w ShamanWipe na sprzęcie tej klasy”).

## Co robi

- **Dobiera najmocniejszą dostępną metodę dla każdego dysku** wg stałej tabeli decyzji (niżej): NVMe Sanitize
  (crypto / block / overwrite), NVMe Format (SES=2 / SES=1), ATA SANITIZE (crypto scramble / block erase /
  overwrite), ATA SECURITY ERASE UNIT (enhanced / normal), SCSI/SAS SANITIZE, eMMC discard + SANITIZE, a w ostateczności
  nadpis przez hosta. Kilka dysków kasuje równolegle.
- **Najpierw przygotowuje dysk.** Ukryte obszary (HPA/DCO) wykrywa i przed kasowaniem przywraca pełną pojemność.
  Gdy przywrócenie się nie uda, wolno użyć wyłącznie metod firmware (nadpis przez hosta ominąłby ukryty obszar);
  gdy i one zawiodą, dysk kończy jako `FAILED`. Dysk ATA w stanie „frozen” odmraża krótkim uśpieniem komputera,
  gdy planowaną metodą jest Security Erase, a komputer obsługuje uśpienie do RAM.
- **Sprawdza wynik, zamiast ufać kodowi wyjścia.** Przed kasowaniem sprzętowym zapisuje 512 losowych znaczników po
  64 KiB rozłożonych po całym dysku; po kasowaniu każdy musi zniknąć, a na dysku nie może zostać sygnatura systemu
  plików. Po nadpisie czyta cały dysk (każdy bajt = 0x00). Dane, które przetrwały — znacznik na miejscu, niezerowy
  blok — zawsze dają `FAILED`.
- **Uczciwie klasyfikuje** wg NIST SP 800-88r2 (wrzesień 2025): `PURGE` tylko dla poleceń sanitize i kasowania
  kryptograficznego, `CLEAR` dla nadpisu, ATA Security Erase i NVMe Format bez kasowania kryptograficznego, `NONE`
  dla mostka USB bez przepustowości ATA i dla wolumenów RAID sprzętowego. Klasa opisuje technikę; to, czy wynik
  jest potwierdzony, mówi status: `ERASED` (skasowany), `ERASED_WITH_WARNINGS` (skasowany z zastrzeżeniem),
  `UNCONFIRMED` (niepotwierdzony), `FAILED` (niepowodzenie).
- **Zapisuje podpisany raport** na partycji `SW-REPORTS` pendrive'a: `report.pdf`, `report.json`, `report.csv`,
  `report.xml`, SMART przed i po, pełny dziennik poleceń, `MANIFEST.sha256` i podpis Ed25519 manifestu. Klucz
  podpisu jest zaszyfrowany hasłem, które wpisuje operator; przed kasowaniem program robi próbny podpis, a bez
  działającego klucza raport mówi na pierwszej stronie, że jest niepodpisany.
- **Pilnuje przed pomyłką:** nośnik startowy i zamontowane dyski są chronione; kasowanie ręczne wymaga wpisania
  `KASUJ N`; numer seryjny i rozmiar dysku są odczytywane ponownie przed jego krokami niszczącymi, a niezgodność
  przerywa kasowanie tego dysku; każde polecenie niszczące trafia do dziennika, zanim ruszy, a po następnym starcie
  widać operacje niedokończone (gdy dziennik leży na `SW-REPORTS`).
- **Tryb AUTOMAT** do serii: wybierany z podmenu startowego (nigdy domyślny), pokazuje listę celów i odlicza 60 s;
  dowolny klawisz na dowolnej konsoli przerywa — do chwili, gdy kasowanie ruszy. Nie wystartuje bez zapisywalnej
  partycji `SW-REPORTS` ani wtedy, gdy nie umie jednoznacznie wskazać nośnika startowego; wolumeny RAID sprzętowego
  pomija.
- **Poza tym:** tryb inwentarza i SMART (niczego nie kasuje), `nwipe` dla innych standardów nadpisu (DoD, Gutmann,
  RCMP…), `sedutil-cli` do PSID revert dysków samoszyfrujących, rozruch BIOS i UEFI (podpisane przez Debiana shim
  i GRUB), interfejs po angielsku i po polsku.

## Tabela decyzji

`tests/test_dobor.py` sprawdza kod wobec tej tabeli. Kolejność = preferencja; rezerwa rusza tylko wtedy, gdy
poprzednia metoda zawiedzie, a każda metoda — pierwsza czy rezerwowa — tylko wtedy, gdy dysk zgłasza jej obsługę.

| Przypadek | Pierwsza technika | Rezerwy (gdy obsługiwane) | Klasa |
|---|---|---|---|
| NVMe, Sanitize z crypto erase | Sanitize Crypto Erase | Sanitize Block → Sanitize Overwrite → Format SES=2 → Format SES=1 → nadpis hosta | PURGE (CE) |
| NVMe, Sanitize block erase | Sanitize Block Erase | Format SES=2 → SES=1 → nadpis hosta | PURGE |
| NVMe bez Sanitize, Format z crypto erase | Format SES=2 | SES=1 → nadpis hosta | PURGE (CE) |
| NVMe bez Sanitize i bez crypto | Format SES=1 | nadpis hosta | CLEAR |
| SATA SSD, Sanitize crypto | ATA SANITIZE crypto scramble | block erase → Sanitize overwrite → enhanced SE → normal SE → nadpis hosta | PURGE (CE) |
| SATA SSD, Sanitize block | ATA SANITIZE block erase | Sanitize overwrite → enhanced SE → normal SE → nadpis hosta | PURGE |
| SATA SSD, tylko Security Erase | enhanced SE (normal SE, gdy enhanced nieobsługiwane) | normal SE → nadpis hosta | CLEAR |
| SATA SSD „frozen” | uśpienie, potem jak wyżej | nadal frozen → bez Security Erase; następna metoda z tabeli | CLEAR |
| SATA HDD z Sanitize | ATA SANITIZE crypto / overwrite (bez block erase na HDD) | enhanced SE → normal SE → nadpis hosta | PURGE |
| SATA HDD, tylko Security Erase | enhanced (albo normal) SE | normal SE → nadpis hosta | CLEAR |
| HDD bez Security Erase | nadpis zerami + pełny odczyt | — | CLEAR |
| SAS/SCSI z Sanitize | SCSI SANITIZE crypto / block (nie na HDD) / overwrite | nadpis hosta | PURGE |
| Mostek USB z SAT | jak SATA | | |
| Mostek USB bez SAT | SCSI SANITIZE, gdy mostek go zgłasza, inaczej nadpis hosta | — | NONE → `UNCONFIRMED` (nadpis) |
| eMMC | discard + MMC SANITIZE + nadpis zerami | — | CLEAR |
| Wolumen RAID sprzętowego | ręcznie: nadpis wolumenu; AUTOMAT: pomija | — | NONE → `UNCONFIRMED` |
| Dysk zablokowany hasłem ATA | — | — | odmowa, nigdy nie nadpisywany |
| Nie udało się przywrócić HPA/DCO | tylko metody firmware | bez nadpisu hosta | jak metoda; `FAILED`, gdy żadna nie zadziała |

`ERASED_WITH_WARNINGS` to skasowanie ze znanym ograniczeniem, na przykład: nośnik flash skasowany tylko nadpisem
hosta (zapas komórek nieobjęty, NIST SP 800-88r2 §4.5.2), HDD z przemapowanymi sektorami (atrybut SMART 5)
skasowany tylko nadpisem hosta, numer seryjny odczytany z mostka USB zamiast z dysku, licznik SMART, który urósł
w trakcie, albo ocena zdrowia SMART FAILED.

## Zanim zaufasz wynikowi

- **Sprawdzaj każdy dysk, nie koniec przebiegu.** AUTOMAT kasuje dyski, które może, a resztę pomija; koniec
  AUTOMATU, kod wyjścia 0 i automatyczne wyłączenie nie znaczą, że skasowano wszystkie dyski. Porównaj inwentarz
  ze statusami dysków i listą `skipped` w raporcie.
- **`UNCONFIRMED` nie znaczy „nietknięty”.** Dysk mógł zostać częściowo albo całkowicie zniszczony — po prostu nie
  potwierdzono, że jest czysty, i nie wolno go przekazać dalej jako skasowanego.
- **Znaczniki to kontrola próbkowa.** Wyłapią polecenie, które nic nie zrobiło (albo zostawiło dane w miejscach
  próbek); nie dowiodą, że kasowanie firmware objęło każdy blok między próbkami. Wewnętrznej jakości kasowania
  kryptograficznego nie da się zmierzyć z zewnątrz (NIST SP 800-88r2 §3.2).
- **NVMe Sanitize kasuje cały kontroler**, ze wszystkimi namespace, także nieprzyłączonymi.
- **Nie podłączaj, nie odłączaj i nie zamieniaj dysków w trakcie przebiegu.** Kontrola tożsamości porównuje numer
  seryjny i rozmiar; dysk bez numeru seryjnego porównuje tylko po rozmiarze. `nwipe` ma własne kontrole, nie te.
- **Poprawny podpis dowodzi, że raport jest nienaruszony, nie że kasowanie się udało.** `shamanwipe weryfikuj`
  używa klucza zapisanego w raporcie, chyba że `--klucz` wskaże Twoją zaufaną kopię — porównaj odcisk klucza
  z PDF z kluczem, który przechowujesz.
- **Bez `SW-REPORTS` tryb ręczny i wiersz poleceń nadal kasują**, ale raport i dziennik operacji zostają w pamięci
  RAM (program ostrzega) i znikają po wyłączeniu.

## Budowa

Skrypty budowy są pisane pod **macOS na Apple silicon** z [Colimą](https://github.com/abiosoft/colima): ISO powstaje
w `live-build` w kontenerze Debian 13 amd64 uruchomionym przez Rosettę.

```sh
brew install colima docker qemu openssl@3
./build.sh                      # -> out/shamanwipe-<wersja>-amd64.iso (+ .sha256, .packages)
```

`build.sh` uruchamia własny profil Colimy `shamanwipe`, nie zmieniając domyślnego kontekstu Dockera. Po pracy:
`colima stop shamanwipe`. Budowa przerywa się, gdy w obrazie brakuje wymaganego pakietu albo trafił do niego
`mdadm`, `lvm2` lub `cryptsetup` (złożyłyby albo odblokowały dyski, które za chwilę mają zostać skasowane).

## Przygotowanie pendrive'a

```sh
scripts/make-usb.sh image                 # ISO + partycja SW-REPORTS + nowy klucz podpisu (pyta o hasło)
scripts/make-usb.sh write /dev/diskN      # tylko USB; potwierdzenie „WRITE diskN”; sprawdzenie odczytem
scripts/make-usb.sh verify /dev/diskN     # ponowne sprawdzenie nagranego pendrive'a
```

Każde `image` tworzy nową parę kluczy i kładzie klucz publiczny do `keys/` (poza repozytorium); pendrive'y nagrane
z jednego obrazu mają ten sam klucz. Hasło klucza trzymaj w menedżerze haseł — bez niego raporty zapisują się bez
podpisu. Uzupełnij `operator.conf` na partycji `SW-REPORTS` (`name`, `title`, `organization`, `location`,
`contact`); te pola trafiają do każdego raportu.

## Użycie

Uruchom komputer z pendrive'a i wybierz pozycję menu: tryb ręczny **English** albo **Polski** (domyślnie
angielski), sam inwentarz albo podmenu **AUTO**. Program startuje jednocześnie na konsoli lokalnej i szeregowej
(`ttyS0`, 115200 b/s).

Z powłoki root:

```sh
shamanwipe lista                                          # dyski i metoda, która zostałaby użyta (tylko odczyt)
shamanwipe kasuj --dysk /dev/sdb --potwierdzam "KASUJ 1"  # kasowanie bez menu
shamanwipe weryfikuj /mnt/sw-reports/reports/<raport>     # sumy i podpis raportu
shamanwipe usb-bot                                        # mostek UAS na BOT, żeby przechodziły polecenia ATA
```

Działają też polecenia angielskie (`list`, `erase --disk … --confirm "ERASE 1"`, `verify`); `SW_LANG=pl`
przełącza wiersz poleceń na polski. Klucze raportu, nagłówki CSV i kody statusów są takie same w obu językach.

### Weryfikacja raportu na innym komputerze

```sh
openssl pkeyutl -verify -pubin -inkey <zaufany klucz publiczny> -rawin -in MANIFEST.sha256 -sigfile MANIFEST.sha256.sig
sha256sum -c MANIFEST.sha256
```

Potrzebny OpenSSL 3 (Ed25519 z `-rawin`); LibreSSL z macOS tego nie umie — użyj `openssl@3` z Homebrew.

## Testy

```sh
SW_LANG=pl python3 -I tests/test_dobor.py     # tabela decyzji, statusy, logika przebiegu (także z SW_LANG=en)
python3 -I tests/mutacje.py                    # stały zestaw celowych błędów — każdy musi zaczerwienić testy
tests/test_urzadzenia.sh                       # urządzenia loop w kontenerze: kasowanie, dyski-oszusty, podpis, konsole
tests/mutacje_konsole.sh                       # celowe błędy w logice konsol i blokady muszą zostać wyłapane
tests/test_check_packages.sh                   # bramka składu obrazu musi oblać zepsutą listę pakietów
tests/qemu-test.sh                             # prawdziwe ISO w QEMU: BIOS/UEFI × płyta/USB, AUTOMAT, raporty
```

Testy w kontenerze widzą wyłącznie urządzenia loop (`SW_TEST_TYLKO_LOOP=1`); bez tej zmiennej program ignoruje
wszystkie haki testowe.

## Ograniczenia

- Bez rozruchu sieciowego, bez centralnego serwera raportów, bez certyfikacji strony trzeciej. Raport pisze
  „metoda wg NIST SP 800-88r2”, nigdy „certyfikowane”.
- Wiele kieszeni USB blokuje polecenia ATA/NVMe. Mostek bez SAT zwykle pozwala tylko na nadpis (`UNCONFIRMED`);
  niektóre kieszenie NVMe w ogóle odrzucają Format i Sanitize — wtedy dysk do gniazda M.2.
- Dysk zablokowany hasłem ATA poprzedniego właściciela jest odrzucany: bez hasła user/master albo PSID revert
  (`sedutil-cli`, PSID z naklejki dysku) nie da się go skasować. Gdy firmware odrzuci polecenie (np. dysk
  samoszyfrujący), program próbuje rezerw z tabeli.
- Na czas ATA Security Erase hasło dysku to stała, jawna wartość `SHAMANWIPE`, żeby dysk przerwany zanikiem
  zasilania dało się odzyskać: `hdparm --user-master u --security-unlock SHAMANWIPE /dev/sdX`, potem
  `hdparm --user-master u --security-disable SHAMANWIPE /dev/sdX`, potem sprawdzić `hdparm -I /dev/sdX`
  (Security: not enabled, not locked).
- Secure Boot nie był jeszcze sprawdzony na prawdziwym sprzęcie.

## Licencja

Copyright © Shamans of Silicon (Szamani Krzemu).

ShamanWipe jest wolnym oprogramowaniem: można go rozpowszechniać i zmieniać na warunkach GNU General Public License
w wersji 3 (`GPL-3.0-only`), zob. [LICENSE](LICENSE). Bez JAKIEJKOLWIEK gwarancji — skasowanie niewłaściwego dysku
jest nieodwracalne.

Nazwa i logo Shamans of Silicon / Szamani Krzemu są znakami towarowymi właściciela i nie są objęte licencją GPL.

Komentarze w kodzie źródłowym są po polsku.
