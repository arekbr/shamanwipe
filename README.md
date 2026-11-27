<p align="center"><img src="assets/logo-tile.png" width="200" alt="Shamans of Silicon"></p>

# ShamanWipe

**Bootable Debian 13 live system for secure disk erasure** — hardware sanitize commands for SSD/NVMe where the
drive supports them, verified overwrite where it does not, and a signed report (PDF, JSON, CSV, XML) for every
erasure it performs.

[Polski](README.pl.md) · English

> Status: **0.1.0, early release.** The whole flow is tested in containers and in QEMU (BIOS and UEFI, CD and USB).
> Firmware erase commands are only as good as the drive firmware. On real hardware one technique has been verified
> so far: ATA SANITIZE BLOCK ERASE, on a Samsung PM871b SATA SSD behind a USB–SATA bridge (the drive reported the
> sanitize operation as completed without error, and none of the 512 markers survived). When the technique listed
> in a report is any other firmware technique, the PDF, JSON and XML report says so explicitly ("Technique not yet
> verified in ShamanWipe on real hardware (…)").

## What it does

- **Chooses the strongest available method for each disk** from a fixed decision table (below): NVMe Sanitize
  (crypto / block / overwrite), NVMe Format (SES=2 / SES=1), ATA SANITIZE (crypto scramble / block erase /
  overwrite), ATA SECURITY ERASE UNIT (enhanced / normal), SCSI/SAS SANITIZE, eMMC discard + SANITIZE, and a host
  overwrite as the last resort. Several disks are erased in parallel.
- **Prepares the drive first.** Hidden areas (HPA/DCO) are detected and the full capacity is restored before
  erasure. If restoring fails, only firmware methods may run (a host overwrite would miss the hidden area); if they
  fail too, the disk ends as `FAILED`. A "frozen" ATA drive is suspended briefly to unfreeze it when Security Erase
  is the planned method and the computer supports suspend-to-RAM. Security Erase starts only after a fresh
  IDENTIFY, read right before it, confirms "not frozen" — also when it is only a fallback; a frozen drive, a
  missing flag or a failed read means it is skipped.
- **Checks the result instead of trusting the exit code.** Before a firmware erase (except on eMMC) it writes 512
  random 64 KiB markers spread across the disk; every one of them must be gone afterwards, and the disk must carry
  no filesystem signatures. An overwrite and the eMMC procedure end with a full read-back (every byte must be
  0x00). Data that survived — a marker still in place, a non-zero block — always makes the result `FAILED`.
- **Classifies honestly** per NIST SP 800-88r2 (September 2025): `PURGE` only for dedicated sanitize commands and
  cryptographic erase, `CLEAR` for overwrite, ATA Security Erase and NVMe Format without crypto erase, `NONE` for a
  USB bridge that passes neither ATA nor SCSI Sanitize commands and for hardware RAID volumes. The class describes the technique; whether the
  result is confirmed is told by the status: `ERASED`, `ERASED_WITH_WARNINGS`, `UNCONFIRMED`, `FAILED`.
- **Writes a signed report** to the `SW-REPORTS` partition of the USB stick: `report.pdf`, `report.json`,
  `report.csv`, `report.xml`, SMART before/after, the full command log, `MANIFEST.sha256` and an Ed25519 signature
  over the manifest. The signing key is encrypted with a passphrase typed by the operator; the key is test-signed
  before erasure, and without a working key the report says "unsigned" on its first page.
- **Guards against accidents:** the boot medium and mounted disks are protected; manual erase requires typing
  `ERASE N`; the serial number and size of a disk are re-read before its destructive steps and a mismatch aborts
  the erasure of that disk; every destructive command is written to the operations log before it starts, and
  unfinished operations are shown after the next boot (when the log is on `SW-REPORTS`; if the log cannot be
  written, the erasure still goes on and the error is recorded only in `run.log`).
- **AUTO mode** for batches: chosen from a boot submenu (never the default), lists the targets, counts down 60 s;
  any key on any console aborts the countdown (another console can abort already while the key passphrase is being
  asked). After the countdown the program offers no safe way to cancel the run — killing the process does not stop
  a firmware command already sent to a drive. It refuses to start without a writable `SW-REPORTS`
  partition or when the boot medium cannot be identified unambiguously, and it skips hardware RAID volumes.
- **Also included:** inventory and SMART mode (erases nothing), `nwipe` for other overwrite standards (DoD, Gutmann,
  RCMP…; it writes its own PDF report and log, not the signed ShamanWipe report), `sedutil-cli` for PSID revert of self-encrypting drives, BIOS and UEFI boot (Debian's signed shim and
  GRUB), English and Polish user interface.

## Decision table

`tests/test_dobor.py` checks the code against this table. Order = preference; a fallback is used only when the
previous method fails, and every method — first or fallback — only when the drive reports support for it. The one
exception is eMMC: discard and MMC SANITIZE are attempted without a support check; a failed SANITIZE adds a warning
and the zero overwrite still runs.

| Case | First technique | Fallbacks (if supported) | Class |
|---|---|---|---|
| NVMe, Sanitize with crypto erase | Sanitize Crypto Erase | Sanitize Block → Sanitize Overwrite → Format SES=2 → Format SES=1 → host overwrite | PURGE (CE) |
| NVMe, Sanitize block erase | Sanitize Block Erase | Sanitize Overwrite → Format SES=2 → SES=1 → host overwrite | PURGE |
| NVMe without Sanitize, Format with crypto erase | Format SES=2 | SES=1 → host overwrite | PURGE (CE) |
| NVMe without Sanitize and crypto | Format SES=1 | host overwrite | CLEAR |
| SATA SSD, Sanitize crypto | ATA SANITIZE crypto scramble | block erase → Sanitize overwrite → enhanced SE → normal SE → host overwrite | PURGE (CE) |
| SATA SSD, Sanitize block | ATA SANITIZE block erase | Sanitize overwrite → enhanced SE → normal SE → host overwrite | PURGE |
| SATA SSD, Security Erase only | enhanced SE (normal SE if enhanced is not supported) | normal SE → host overwrite | CLEAR |
| SATA SSD "frozen", Security Erase planned | suspend, then as above | still frozen → no Security Erase at all (fallbacks included): host overwrite | CLEAR |
| SATA HDD with Sanitize | ATA SANITIZE crypto / overwrite (no block erase on HDD) | Sanitize overwrite (after crypto) → enhanced SE → normal SE → host overwrite | PURGE |
| SATA HDD, Security Erase only | enhanced (or normal) SE | normal SE → host overwrite | CLEAR |
| HDD without Security Erase | zero overwrite + full read-back | — | CLEAR |
| SAS/SCSI with Sanitize | SCSI SANITIZE crypto / block (not on HDD) / overwrite | the other supported SCSI SANITIZE variants → host overwrite | PURGE |
| USB bridge with SAT | as SATA | | |
| USB bridge without SAT | SCSI SANITIZE if the bridge reports it (then as SAS/SCSI), otherwise host overwrite | — | as SAS/SCSI; neither ATA nor SCSI Sanitize reported: NONE → `UNCONFIRMED` |
| eMMC | discard + MMC SANITIZE (no support check) + zero overwrite + full read-back | — | CLEAR |
| Hardware RAID volume | manual: volume overwrite; AUTO: skipped | — | NONE → `UNCONFIRMED` |
| Drive locked with an ATA password | — | — | refused, never overwritten |
| HPA/DCO could not be restored | firmware methods only | no host overwrite | as the method; `FAILED` if none works |

`ERASED_WITH_WARNINGS` means erased with a known limitation, for example: flash media erased by host overwrite only (spare
cells are not covered, NIST SP 800-88r2 §4.5.2), an HDD with reallocated sectors erased by host overwrite only,
a serial number read from the USB bridge instead of the drive, a SMART counter that grew during the run, or SMART
health FAILED.

## Before you trust a result

- **Check every disk, not the end of the run.** AUTO erases the disks it can and skips the rest; the end of AUTO,
  exit code 0 and the automatic power-off do not mean that every disk was erased. Compare the inventory with the
  per-disk statuses and the `skipped` list in the report.
- **`UNCONFIRMED` does not mean "untouched".** The disk may be partly or fully destroyed — it is simply not confirmed
  clean, and must not be passed on as erased.
- **Markers are a sample check.** They catch a command that did nothing (or left data in the sampled places); they
  cannot prove that a firmware erase covered every block between the samples. The internal quality of a crypto
  erase cannot be measured from the outside (NIST SP 800-88r2 §3.2).
- **NVMe Sanitize erases the whole controller**, including all namespaces, also those not attached.
- **Do not plug, unplug or swap disks during a run.** The identity check compares serial number and size; a disk
  without a serial number is compared by size only. `nwipe` runs its own checks, not these.
- **A valid signature proves the report is intact, not that the erasure succeeded.** `shamanwipe verify` uses the
  key stored in the report unless `--key` points to your trusted copy — compare the key fingerprint printed in the
  PDF with the key you kept.
- **Without `SW-REPORTS` the manual mode and the command line still erase**, but the report and the operations log
  stay in RAM (the program warns) and are lost at power-off.

## Building

The build scripts target **macOS on Apple silicon** with [Colima](https://github.com/abiosoft/colima): the ISO is
built with `live-build` in a Debian 13 amd64 container running under Rosetta.

```sh
brew install colima docker qemu openssl@3
./build.sh                      # -> out/shamanwipe-<version>-amd64.iso (+ .sha256, .packages)
```

`build.sh` starts its own Colima profile `shamanwipe` without changing your default Docker context. Stop it after
work with `colima stop shamanwipe`. The build fails if a required package is missing or if `mdadm`, `lvm2` or
`cryptsetup` got into the image (they would assemble or unlock the very disks that are about to be erased).

## Preparing the USB stick

```sh
scripts/make-usb.sh image                 # ISO + SW-REPORTS partition + a new signing key (asks for a passphrase)
scripts/make-usb.sh write /dev/diskN      # USB only; type "WRITE diskN" to confirm; verified by reading back
scripts/make-usb.sh verify /dev/diskN     # re-check an already written stick
```

Every `image` run creates a new key pair and puts the public key into `keys/` (kept out of the repository);
sticks written from the same image share the key. Keep the key passphrase in your password manager — without it
reports are written unsigned. Fill in `operator.conf` on the `SW-REPORTS` partition (`name`, `title`,
`organization`, `location`, `contact`); these fields go into every report.

## Using it

Boot the computer from the stick and pick a menu entry: **English** or **Polski** manual mode (default:
English), inventory only, or the **AUTO** submenu. The program starts on the local console and on the serial
console (`ttyS0`, 115200 baud) at the same time.

From the root shell:

```sh
shamanwipe list                                         # disks and the method that would be used (read-only)
shamanwipe erase --disk /dev/sdb --confirm "ERASE 1"    # erase without the menu
shamanwipe verify /mnt/sw-reports/reports/<report>      # check checksums and signature
shamanwipe usb-bot                                      # set UAS bridges to BOT mode; then unplug and replug them
```

Polish command aliases (`lista`, `kasuj`, `weryfikuj`) and `KASUJ N` are accepted as well. `SW_LANG=pl` switches
the command-line interface to Polish. Report keys, CSV headers and status codes are the same in both languages.

### Verifying a report elsewhere

```sh
openssl pkeyutl -verify -pubin -inkey <your trusted public key> -rawin -in MANIFEST.sha256 -sigfile MANIFEST.sha256.sig
sha256sum -c MANIFEST.sha256
```

OpenSSL 3 is required (Ed25519 with `-rawin`); the LibreSSL shipped with macOS cannot do it — use Homebrew's
`openssl@3`.

## Tests

```sh
SW_LANG=en python3 -I tests/test_dobor.py     # decision table, statuses, run logic (also with SW_LANG=pl)
python3 -I tests/mutacje.py                    # a fixed set of deliberate bugs, each must turn the tests red
tests/test_urzadzenia.sh                       # loop devices in a container: erase, cheating disks, signatures, consoles
tests/mutacje_konsole.sh                       # deliberate bugs in the console/lock logic must be caught
tests/test_check_packages.sh                   # the image composition gate must fail on a broken package list
tests/qemu-test.sh                             # the real ISO in QEMU: BIOS/UEFI × CD/USB, AUTO, reports
```

Container tests see only loop devices (`SW_TEST_TYLKO_LOOP=1`); every test hook in the program is ignored without
that variable.

## Limitations

- No network boot, no central report server, no third-party certification. The report says "method per NIST
  SP 800-88r2", never "certified".
- Many USB enclosures block ATA/NVMe admin commands. A bridge without SAT usually allows only an overwrite
  (`UNCONFIRMED`); some NVMe enclosures reject Format and Sanitize altogether — put the drive into an M.2 slot.
- A drive locked with a previous owner's ATA password is refused: it cannot be erased without the user/master
  password or a PSID revert (`sedutil-cli`, with the PSID printed on the drive label). When a firmware command is
  rejected (e.g. by a self-encrypting drive), the fallbacks from the table are tried.
- During ATA Security Erase the drive password is set to the fixed, public value `SHAMANWIPE`, so that a drive
  interrupted by a power loss can be recovered: `hdparm --user-master u --security-unlock SHAMANWIPE /dev/sdX`,
  then `hdparm --user-master u --security-disable SHAMANWIPE /dev/sdX`, then check `hdparm -I /dev/sdX`
  (Security: not enabled, not locked).
- Secure Boot has not been tested on real hardware yet.

## License

Copyright © Shamans of Silicon (Szamani Krzemu).

ShamanWipe is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License version 3 (`GPL-3.0-only`), see [LICENSE](LICENSE). It comes with ABSOLUTELY NO WARRANTY — erasing the
wrong disk is irreversible.

The Shamans of Silicon / Szamani Krzemu name and logo are trademarks of their owner and are not licensed under
the GPL.

Source code comments are written in Polish.
