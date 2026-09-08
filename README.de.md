# Genshin Code Monitor

Lokale Windows-App zur Überwachung von Genshin-Impact-Promocode-Quellen mit automatischer Einlösung neuer Codes über die Hoyolab API. Alles bleibt auf Ihrem PC: SQLite-Datenbank, verschlüsselte Cookies, keine Telemetrie, keine Cloud.

> Lesen auf: [English](README.md) · [Русский](README.ru.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [中文](README.zh.md)

## Funktionen

- **Hintergrundüberwachung** — prüft Quellen alle N Minuten (konfigurierbar, Standard 15)
- **Auto-Einlösung** — löst neue Codes über die Hoyolab `webExchangeCdkey` API ein (opt-in, pro Konto)
- **Multi-Source** — Wiki, Wiki-API, Community-JSON-APIs, Guide-Seiten (16 Presets)
- **Multi-Account** — jedes Konto hat eigene verschlüsselte Cookies und eigenen Schalter
- **Statistik** — gesamt / eingelöst / ausstehend, pro Quelle, Einlöseprotokoll
- **Web UI** — lokales Dashboard unter `http://127.0.0.1:8000` in 6 Sprachen
- **System Tray** — Symbol mit Ein/Aus, Scanintervall-Menü, Einstellungen per Klick
- **Verschlüsselte Cookies** — Fernet (AES-128), Schlüssel in env / OS-Keyring / lokaler Datei
- **Autostart** — optionaler Windows-Login-Autostart

## Quellen (live geprüft)

| Quelle | Typ | Status |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | Kann 403 liefern (Fandom-Schutz) |
| Genshin Wiki API | JSON | Funktioniert |
| `hoyo-codes.seria.moe` | JSON API | Funktioniert |
| `api.ennead.cc` (2 Endpunkte) | JSON API | Funktioniert |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS-Guides | Funktionieren |

## Installation

Python 3.11+ erforderlich.

```powershell
pip install -e .
# Playwright-Browser für JS-Quellen (optional)
python -m playwright install chromium
```

## Verwendung

```powershell
# Konto hinzufügen + Cookies automatisch erfassen (Browser öffnet sich, einmal einloggen)
genshin-code-monitor accounts add main <UID> <REGION>   # Region: os_usa / os_euro / os_asia / os_cht
genshin-code-monitor accounts login main

# Auto-Einlösung aktivieren (oder Schalter pro Konto in der Web UI)
genshin-code-monitor config set redemption_enabled true

# Tray-Modus (empfohlen) / Einzelprüfung / Web UI
genshin-code-monitor tray
genshin-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

Web UI: `http://127.0.0.1:8000` — Dashboard, Sources, Accounts, Config (Sprachumschalter EN/RU/DE/FR/JA/ZH in der Seitenleiste).

## So funktioniert die Einlösung

1. Der Planer fragt aktivierte Quellen ab, extrahiert Codes (`[A-Z0-9]{8,14}`), speichert neue.
2. Für jedes Konto mit aktivierter Auto-Einlösung: `GET webExchangeCdkey` mit Konto-Cookies, 8s Pause.
3. Ergebnis wird protokolliert: `success` → Done + Belohnung; `-2017/-2018` → bereits eingelöst (zählt als Done); `-2001` abgelaufen, `-2003` ungültig/nur China.

## FAQ

- **Code bleibt Pending?** Cookies prüfen (laufen ab), `redemption_enabled`, Kontoschalter und Fehler im Einlöseprotokoll.
- **`-1071 "Please log in"`?** `accounts login` wiederholen — Cookie-Satz unvollständig.
- **Wo sind die Daten?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Für Backup `data/` kopieren.

## Autor & Unterstützung

Siehe About-Block im Dashboard der App (Kontakte, Spendenlinks und Krypto-Adressen werden dort konfiguriert).

## Lizenz

MIT
