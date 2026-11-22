# HoYo Code Monitor

[![Release](https://img.shields.io/github/v/release/retvil/hoyo-code-monitor?sort=date)](https://github.com/retvil/hoyo-code-monitor/releases) [![License MIT](https://img.shields.io/badge/license-MIT-green)](../LICENSE) [![Platform Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/retvil/hoyo-code-monitor/releases)

[🇬🇧 English](../README.md) | [🇷🇺 Русский](README.ru.md) | [🇺🇦 Українська](README.uk.md) | [🇰🇿 Қазақша](README.kk.md) | [🇩🇪 Deutsch](README.de.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇯🇵 日本語](README.ja.md) | [🇵🇱 Polski](README.pl.md) | **🇹🇷 Türkçe** | [🇨🇳 中文](README.zh.md) | [🇹🇼 繁體中文](README.zh-TW.md)

## Bu nedir?

HoYoverse oyunları düzenli olarak süresi sınırlı promosyon kodları yayınlar — ve hızla sona erer. **HoYo Code Monitor** 5 oyunda 23 kod kaynağını (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) izler ve yeni kodları hesaplarınızda otomatik olarak kullanır. Her şey bilgisayarınızda yerel olarak çalışır: SQLite veritabanı, şifrelenmiş çerezler, telemetri yok, bulut yok.

### Nasıl çalışır

1. Zamanlayıcı etkin kaynakları sorgular, kodları çıkarır (`[A-Z0-9]{8,14}`) ve yenilerini kaydeder.
2. Otomatik kullanım açık her hesap için: hesabın çerezleriyle `GET webExchangeCdkey`, kullanımlar arasında yapılandırılabilir bekleme (varsayılan 8 sn).
3. Sonuç kaydedilir: `success` → Done + ödül; `-2017/-2018` → zaten kullanılmış (Done sayılır); `-2001` süresi dolmuş, `-2003` geçersiz/sadece Çin.
4. Günlük HoYoLAB girişleri kendi programlarında çalışır (varsayılan 04:00 + sapma): hesap × oyun başına `info → sign → home`, aynı çerezlerle, sonuçlar Girişler sayfasında.
5. Bir giriş süresi dolmuş çerezler yüzünden başarısız olursa, zamanlayıcı bunları kayıtlı tarayıcı profilinden **headless modda otomatik olarak yenileyebilir** (isteğe bağlı anahtar, hesap başına bekleme süresi) — kayıtlı oturum geçerli olduğu sürece manuel yeniden giriş gerekmez.

## Özellikler

- **Arka plan izleme** — kaynakları her N dakikada bir kontrol eder (yapılandırılabilir, varsayılan 15)
- **Otomatik kullanım** — yeni kodları Hoyolab `webExchangeCdkey` API'si ile kullanır (isteğe bağlı, hesap başına)
- **Günlük girişler** — 5 oyunun tamamı için HoYoLAB'da otomatik giriş (isteğe bağlı, hesap başına, kendi programı, idempotent)
- **Çok kaynaklı** — Wiki, Wiki API, topluluk JSON API'leri, rehber siteleri (23 ön ayar)
- **Çok hesaplı** — her hesabın kendi şifrelenmiş çerezleri ve kendi kullanım anahtarı vardır
- **Otomatik çerez yenileme** — giriş süresi dolmuş çerezler yüzünden başarısız olursa, kayıtlı tarayıcı profilinden headless modda yeniden yakalanır
- **Etkin oyun filtresi** — zamanlayıcı hesabın etkinleştirmediği oyunları atlar
- **Kaynak başına "etkin" durumu** — başarıyla doğrulanan kaynaklar "etkin" olarak gösterilir
- **İstatistikler** — toplam / kullanılan / başarısız, kaynak bazında dağılım, kullanım günlüğü
- **Web UI** — `http://127.0.0.1:8000` adresinde yerel panel, 6 dilde
- **Sistem tepsisi** — aç/kapat simgesi, tarama aralığı alt menüsü, tek tıkla ayarlar
- **Şifrelenmiş çerezler** — Fernet (AES-128), anahtar env / sistem kasasında / yerel dosyada
- **Koyu tema** — kenar çubuğunda Açık/Koyu anahtarı; seçim tarayıcı başına saklanır
- **Otomatik başlatma** — Windows'a girişte başlar (varsayılan olarak açık)

## Ekran görüntüleri

<details>
<summary>Panel / Kaynaklar / Yapılandırma / Girişler / Hesaplar / Yazar</summary>

| Panel | Kaynaklar | Yapılandırma |
|---|---|---|
| ![Panel](screenshots/dashboard_en.png) | ![Kaynaklar](screenshots/sources_en.png) | ![Yapılandırma](screenshots/config_en.png) |

| Yazar |
|---|
| ![Yazar](screenshots/author_en.png) |

| Girişler | Hesaplar |
|---|---|
| ![Girişler](screenshots/checkins_en.png) | ![Hesaplar](screenshots/accounts_en.png) |

</details>

## Kaynaklar (canlı doğrulandı)

| Kaynak | Tür | Durum |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | May return 403 (Fandom protection) |
| Genshin Wiki API | JSON | Working |
| `hoyo-codes.seria.moe` | JSON API | Working |
| `api.ennead.cc` (x2 endpoints) | JSON API | Working |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS guides | Working |

## Yükleyiciden yükleme

En son sürümü [GitHub Releases](https://github.com/retvil/hoyo-code-monitor/releases) adresinden indirin:

| Dosya | Açıklama |
|---|---|
| `hoyo-code-monitor-X.Y.Z-setup.exe` | Inno Setup yükleyicisi (geçerli kullanıcı için, yönetici hakları gerekmez) |

### Etkileşimli yükleme

1. `.exe` dosyasını çalıştırın — nereye yükleneceğini sorar
2. **İleri**'ye tıklayın — iki bileşen: masaüstü kısayolu ve Windows otomatik başlatma
3. **Yükle**'ye tıklayın — ~30 saniyede hazır. Uygulama sistem tepsisinde başlar.

### Sessiz yükleme (betikler / GPO / SCCM)

```powershell
# Per-user install, no prompts
hoyo-code-monitor-1.5.3-setup.exe /S

# Install to a specific directory
hoyo-code-monitor-1.5.3-setup.exe /S /D=C:\Games\HoYoMonitor

# No desktop shortcut, no autostart
hoyo-code-monitor-1.5.3-setup.exe /S /desktop=no /startup=no
```

### Kaldırma

- **Denetim Masası** → Programlar ve Özellikler → "HoYo Code Monitor" → Kaldır
- **Sessiz**: `uninstall.exe /S`
- Veya yükleme klasörünü ve `HKCU\Software\HoYoCodeMonitor` kayıt defteri anahtarını silin

### Veri konumları (kaldırma/yeniden yükleme arasında korunur)

| Ne | Nerede |
|---|---|
| SQLite database | `%LOCALAPPDATA%\HoYoCodeMonitor\monitor.db` |
| `config.toml` (settings, source definitions) | `%LOCALAPPDATA%\HoYoCodeMonitor\config.toml` |
| Encrypted Fernet key | OS keyring (Windows Credential Manager) |
| Logs | `%LOCALAPPDATA%\HoYoCodeMonitor\logs\` |
| Browser profile (Playwright Chromium) | `%LOCALAPPDATA%\HoYoCodeMonitor\browser-profile\` |

> Büyük sürüm yükseltmesinden önce `data/` + `config.toml` yedeğini alın.

## Hızlı başlangıç

```powershell
# 1. Install and launch - the app lives in the system tray
# 2. Add an account (region: os_usa / os_euro / os_asia / os_cht)
hoyo-code-monitor accounts add main <UID> <REGION>

# 3. Capture cookies once (browser opens, you log in once)
hoyo-code-monitor accounts login main

# 4. Enable auto-redeem (or toggle per account in the Web UI)
hoyo-code-monitor config set redemption_enabled true
```

5. Open the dashboard: `http://127.0.0.1:8000`

## Kaynaktan yükleme

Python 3.11+ gerektirir ([python.org](https://python.org)).

```powershell
pip install -e .
# Playwright browser for JS-rendered sources (optional)
python -m playwright install chromium
```

Tepside çalıştır (önerilir) / tek seferlik kontrol / Web UI:

```powershell
hoyo-code-monitor tray
hoyo-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

## SSS

- **Kod Pending'de mi takılı?** Çerezleri (süreleri dolar), `redemption_enabled`'i, hesap anahtarını ve kullanım günlüğündeki hatayı kontrol edin.
- **`-1071 "Please log in"`?** `accounts login` komutunu tekrarlayın — çerez seti eksikti.
- **Veriler nerede?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Yedek için `data/` klasörünü kopyalayın.

## Yazar ve destek

Uygulama panelindeki "Yazar hakkında" bloğuna veya aşağıya bakın:

**Kripto:**

- BTC: `bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97`
- TON: `UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC`
- USDT (TRC20): `TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd`
- USDT (ERC20): `0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C`
- USDT (SOL): `3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG`

## Lisans

MIT
