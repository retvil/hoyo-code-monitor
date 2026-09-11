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
SUPPORT_PATREON: str = ""
SUPPORT_BOOSTY: str = "https://boosty.to/nod33eset/donate"
SUPPORT_KOFI: str = ""
SUPPORT_DONATIONALERTS: str = ""
SUPPORT_CLOUDTIPS: str = ""
SUPPORT_DONATEPAY: str = ""
SUPPORT_BITCOIN: str = ""
SUPPORT_TON: str = "UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC"
SUPPORT_USDT_TRC20: str = ""


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
        "support_bitcoin": SUPPORT_BITCOIN,
        "support_ton": SUPPORT_TON,
        "support_usdt_trc20": SUPPORT_USDT_TRC20,
    }


def has_any() -> bool:
    """Check if any author field is filled."""
    return any(as_dict().values())
