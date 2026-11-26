# Źródła danych testowych

| Plik | Rodzaj | Skąd |
|---|---|---|
| `hdparm-samsung-pm871-0.txt` | prawdziwy | Samsung SSD PM871 256 GB, `hdparm -I` przed kasowaniem |
| `hdparm-goodram-0.txt`, `-1.txt` | prawdziwy | Goodram SSD 1 TB, `hdparm -I` przed Security Erase i po odzyskaniu dostępu |
| `hdparm-crucial-bx500-0.txt` | prawdziwy | Crucial BX500 240 GB, `hdparm -I` przed kasowaniem |
| `hdparm-sanitize-status-crucial-po.txt` | prawdziwy | ten sam Crucial, `hdparm --sanitize-status` po SANITIZE BLOCK ERASE |
| `smart-hdd-reallocated-48.json` | prawdziwy | HDD 8 TB Seagate ST8000VN0022, `smartctl -j`, atrybut 5 (Reallocated_Sector_Ct) = 48 |
| `syntetyczny-*.txt` | syntetyczny | pochodne prawdziwych plików z jedną zmianą opisaną w 1. linii pliku |

W plikach prawdziwych numery seryjne, WWN, czas i ścieżka urządzenia zastąpione wartościami syntetycznymi; reszta
wyjścia narzędzi bez zmian. Bloki `hdparm -I` wycięte z logów z odrzuceniem linii z poleceniami ustawiania hasła ATA.
Przypadek „SSD po Security Erase nie odpowiada na IDENTIFY” jest odtworzony w teście jako pusty wynik IDENTIFY po operacji.
