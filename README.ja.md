# HoYo Code Monitor

原神プロモコードの情報源を監視し、新しいコードをHoYolab APIで自動交換するWindowsローカルアプリ。すべてPC内に保存されます:SQLiteデータベース、暗号化Cookie、テレメトリーなし、クラウドなし。

> 他の言語で読む: [English](README.md) · [Русский](README.ru.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [中文](README.zh.md)

## 機能

- **バックグラウンド監視** — N分ごとにソースを確認 (設定可能、デフォルト15分)
- **自動交換** — HoYolab `webExchangeCdkey` APIで新コードを交換 (オプトイン、アカウント別)
- **マルチソース** — Wiki、Wiki API、コミュニティJSON API、ガイドサイト (16プリセット)
- **マルチアカウント** — アカウントごとに暗号化Cookieと交換スイッチ
- **統計** — 合計 / 交換済み / 保留中、ソース別内訳、交換ログ
- **Web UI** — `http://127.0.0.1:8000` のローカルダッシュボード (6言語対応)
- **システムトレイ** — 有効/無効、スキャン間隔メニュー、ワンクリック設定
- **Cookie暗号化** — Fernet (AES-128)、鍵はenv / OSキーリング / ローカルファイル
- **自動起動** — Windowsログイン時の自動起動 (任意)

## ソース (実動作確認済み)

| ソース | 種類 | 状態 |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | 403の場合あり (Fandom保護) |
| Genshin Wiki API | JSON | 動作 |
| `hoyo-codes.seria.moe` | JSON API | 動作 |
| `api.ennead.cc` (2エンドポイント) | JSON API | 動作 |
| Pocket Tactics、TheClick、Eurogamer、MMO Culture、Playnforge | CSSガイド | 動作 |

## インストール

Python 3.11+ が必要です。

```powershell
pip install -e .
# JSソース用のPlaywrightブラウザ (任意)
python -m playwright install chromium
```

## 使い方

```powershell
# アカウント追加 + Cookie自動取得 (ブラウザが開くので一度ログイン)
genshin-code-monitor accounts add main <UID> <REGION>   # region: os_usa / os_euro / os_asia / os_cht
genshin-code-monitor accounts login main

# 自動交換を有効化 (またはWeb UIでアカウント別に切替)
genshin-code-monitor config set redemption_enabled true

# トレイモード (推奨) / 単発チェック / Web UI
genshin-code-monitor tray
genshin-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

Web UI: `http://127.0.0.1:8000` — Dashboard、Sources、Accounts、Config (サイドバーでEN/RU/DE/FR/JA/ZH切替)。

## 交換の仕組み

1. スケジューラが有効なソースを取得し、コード (`[A-Z0-9]{8,14}`) を抽出して保存。
2. 自動交換ONのアカウントごとにCookie付きで `GET webExchangeCdkey`、8秒間隔。
3. 結果を記録: `success` → Done + 報酬、`-2017/-2018` → 交換済み (Done扱い)、`-2001` 期限切れ、`-2003` 無効/中国限定。

## FAQ

- **Pendingのまま?** Cookie (失効します)、`redemption_enabled`、アカウントのスイッチ、交換ログのエラーを確認。
- **`-1071 "Please log in"`?** `accounts login` を再実行 — Cookieセットが不完全です。
- **データの場所?** `data/monitor.db`、`config.toml`、`logs/`、`data/.key`。バックアップは `data/` をコピー。

## 作者と支援

アプリのダッシュボード内「作者について」ブロックを参照 (連絡先、支援リンク、暗号資産アドレスを設定可能)。

## ライセンス

MIT
