"""Hardcoded author info for HoYo Code Monitor.

These values are compiled into the app and CANNOT be changed from the UI.
Fill in real links before release. Empty values are hidden automatically.
"""

from __future__ import annotations

AUTHOR_NAME: str = "Nod33Eset"
AUTHOR_URL: str = ""
AUTHOR_TELEGRAM: str = "@Nod33Eset"
AUTHOR_EMAIL: str = "sdcloud@mail.ru"
AUTHOR_GITHUB: str = "https://github.com/retvil"

SUPPORT_URL: str = ""
SUPPORT_PATREON: str = "https://www.patreon.com/cw/nod33eset"
SUPPORT_BOOSTY: str = "https://boosty.to/nod33eset/donate"
SUPPORT_KOFI: str = ""
SUPPORT_DONATIONALERTS: str = ""
SUPPORT_CLOUDTIPS: str = "https://pay.cloudtips.ru/p/e6dd5692"
SUPPORT_DONATEPAY: str = "https://widget.donatepay.ru/widgets/page/b0b8a9d022b17d3f4ea9f0754cb136307166db2b10fdaac1b619f2952e11bb52?widget_id=7857855&sum=200"
SUPPORT_DONATE_STREAM: str = "https://donate.stream/Nod33Eset"
SUPPORT_DONATTY: str = "https://donatty.com/nod33eset"
SUPPORT_BITCOIN: str = "bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97"
SUPPORT_TON: str = "UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC"
SUPPORT_USDT_TRC20: str = "TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd"
SUPPORT_USDT_ERC20: str = "0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C"
SUPPORT_USDT_SOL: str = "3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG"


def as_dict() -> dict[str, str]:
    """Return all author fields as dict for templates."""
    return {
        "author_name": AUTHOR_NAME,
        "author_url": AUTHOR_URL,
        "author_telegram": AUTHOR_TELEGRAM,
        "author_email": AUTHOR_EMAIL,
        "author_github": AUTHOR_GITHUB,
        "support_url": SUPPORT_URL,
        "support_patreon": SUPPORT_PATREON,
        "support_boosty": SUPPORT_BOOSTY,
        "support_kofi": SUPPORT_KOFI,
        "support_donationalerts": SUPPORT_DONATIONALERTS,
        "support_cloudtips": SUPPORT_CLOUDTIPS,
        "support_donatepay": SUPPORT_DONATEPAY,
        "support_donate_stream": SUPPORT_DONATE_STREAM,
        "support_donatty": SUPPORT_DONATTY,
        "support_bitcoin": SUPPORT_BITCOIN,
        "support_ton": SUPPORT_TON,
        "support_usdt_trc20": SUPPORT_USDT_TRC20,
        "support_usdt_erc20": SUPPORT_USDT_ERC20,
        "support_usdt_sol": SUPPORT_USDT_SOL,
    }


def has_any() -> bool:
    """Check if any author field is filled."""
    return any(as_dict().values())
