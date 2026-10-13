# HerrHaseGermany Druckerprofil

Dieser Fork ergänzt die Installation anhand von
[KlipperBackup](https://github.com/HerrHaseGermany/KlipperBackup).
Die mitgelieferte Liste stammt aus `printer_data/config/moonraker_update_manager.cfg`
bei Backup-Commit `d2185b63c83a67391d6ade48a89c55c0abc56b58`.

## Bedienung

KIAUH auf dem Linux-Druckerhost als normaler Druckerbenutzer starten:

```bash
./kiauh.sh
```

- **Installation → 9 → A:** Druckerprofil installieren und anschließend die
  Konfiguration aus dem Backup wiederherstellen. Die Service-Liste wird aus dem
  ausgewählten Backup-Stand gelesen.
- **Installation → 9 → 1–11:** einzelne Komponenten aus dem mitgelieferten Profil
  installieren. Diese Einträge ersetzen nicht automatisch die Druckerkonfiguration.
- **Installation → 9 → D / H:** KAMP und Systemabhängigkeiten / Linux-Host-MCU
  installieren.
- **Installation → 10**, **Backup → 10** oder **Druckerprofil → R:**
  „Config aus Backup wiederherstellen“ ohne Neuinstallation der Komponenten.

Als Backup-Stand kann `HEAD` (aktueller Default-Branch), ein Branch, Tag oder
Commit-Hash ausgewählt werden. Das Repository wird jeweils neu in ein temporäres
Verzeichnis geklont. Der verwendete Commit wird angezeigt. Bei einem privaten
Repository muss Git bereits Zugriff haben, beispielsweise über einen Credential
Helper oder eine konfigurierte SSH-URL-Umschreibung.

## Umfang

Die Gesamtinstallation setzt eine einzelne, unbenannte Klipper-/Moonraker-Instanz
unter `~/printer_data` voraus. Sie installiert:

| Bestandteil | Installationsweg |
| --- | --- |
| Klipper und Moonraker | vorhandene KIAUH-Setup-Services |
| Linux-Host-MCU | separater Linux-Build aus Klipper, `klipper-mcu.service` |
| Mainsail | vorhandener KIAUH-Webclient-Installer, Port 80 |
| Mainsail-Config | Repository und `mainsail.cfg`-Verknüpfung |
| Crowsnest | `sudo make install` |
| Sonar | `make config`, `sudo make install` |
| Moonraker Timelapse | `make install` |
| KlipperScreen | `scripts/KlipperScreen-install.sh` |
| Klipper-Backup | `install.sh` mit dessen interaktiver Einrichtung |
| KlipperPLR | `install.sh`; installiert auch `gcode_shell_command` |
| KlipperCameraControl | `install.sh`, nach PLR |
| KlipperLCD | `sudo bash install.sh` aus Artillery-KlipperLCD |
| Calibration Wizard | `install.sh`, nach Mainsail |
| KAMP | Repository und Verknüpfung auf `Configuration` |

Zusätzlich werden `v4l-utils`, `ffmpeg`, `make` und `gcc` installiert. Für den
Calibration Wizard müssen Node.js **20.19+ innerhalb 20.x, 22.12+ innerhalb 22.x
oder neuer als 22** und npm vorhanden sein; dies wird vor der Gesamtinstallation
geprüft. Die jeweiligen Installer fragen weiterhin erforderliche Hardwarewerte,
sudo-Zugang und Klipper-Backup-Zugangsdaten ab. Die Zugangsdaten für künftige
Backups müssen dort eingerichtet werden; das Konfigurationsbackup enthält sie
nicht.

Die Update-Manager-Option `install_script` beschreibt nicht zuverlässig den
Erstinstallationsweg. Deshalb verwendet das Profil explizite Rezepte, insbesondere
für [Crowsnest](https://github.com/mainsail-crew/crowsnest),
[Sonar](https://github.com/mainsail-crew/sonar) und
[Timelapse](https://github.com/mainsail-crew/moonraker-timelapse/blob/main/docs/installation.md).
Unbekannte Komponenten, unerwartete Repository-Adressen und ungeeignete Pfade
brechen die Gesamtinstallation vor Änderungen ab. Neue Komponenten benötigen ein
Rezept in `kiauh/components/printer_profile/profile.py`.

## Wiederherstellung

Vor der Gesamtinstallation wird die vorhandene Konfiguration unter
`~/kiauh_backups/config-before-profile_*` gesichert. Vor dem eigentlichen Austausch
entsteht eine zusätzliche Sicherung unter `~/kiauh_backups/config-before-restore-*`.
Schlägt die Sicherung fehl, wird die Konfiguration nicht ersetzt.

Die Wiederherstellung bereitet die Dateien in einem temporären Verzeichnis auf
und prüft die rekursiven Includes von `printer.cfg` und `moonraker.conf`. Fehlende
feste Includes brechen den Vorgang vor dem Austausch ab. `mainsail.cfg` und `KAMP`
werden aus vorhandenen Installationen neu verknüpft. Bei einer reinen
Wiederherstellung müssen diese Abhängigkeiten also bereits installiert sein.
Beliebige Symlinks im Git-Backup werden nicht übernommen.

Die vorhandene Config wird vollständig durch die Backup-Config ersetzt. Eine
lokal erzeugte `.theme`-Integration bleibt erhalten, wenn das Backup keine eigene
enthält. `/home/biqu` wird in `.cfg`- und `.conf`-Dateien an das aktuelle
Benutzerverzeichnis angepasst. Die KlipperLCD-Origin wird bei Bedarf an den
installierten Git-Remote angepasst; neue KlipperLCD-Checkouts verwenden HTTPS.
Makros, MCU-Seriennummern und SAVE_CONFIG-Kalibrierwerte stammen aus dem Backup.

Aktive betroffene Dienste einschließlich der Backup-Writer werden für den
Austausch gestoppt und anschließend wieder gestartet. Bereits inaktive Dienste
bleiben inaktiv. Scheitert der Dateiaustausch, wird das bisherige Config-Verzeichnis
zurückgesetzt. Scheitert ein Dienststart, wird das gemeldet; die externe Sicherung
bleibt zur manuellen Rücksicherung erhalten. Bereits abgeschlossene Installationen
werden bei einem späteren Installationsfehler nicht automatisch deinstalliert.

## Grenzen der Reproduktion

Das Backup enthält Konfiguration und Update-Manager-Repositories/Branches, aber
keine vollständige Liste der aktuell installierten Software-Commits. Neue
Installationen beziehen die angegebenen Branches bzw. das stabile Mainsail-Release;
passende vorhandene, saubere Checkouts werden unverändert benutzt. Damit werden
Services und Druckerkonfiguration reproduziert, jedoch keine identischen
Softwareversionen garantiert.

Mainboard-Firmware, Betriebssystem, UART-/SPI-/GPIO-Einstellungen und Gerätepfade
müssen zur Hardware passen. Die Mainboard-Firmware wird nicht automatisch geflasht.
Der Linux-Host-MCU-Build nutzt eigene temporäre Build-Dateien und überschreibt die
Klipper-`.config` nicht. Der KlipperLCD-Installer kann die Display-Firmware gemäß
seinem eigenen Ablauf aktualisieren. Nach der Installation müssen Moonraker,
Klipper und die Geräteverbindungen auf dem Druckerhost geprüft werden.
