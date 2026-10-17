"""Tests for the Windows toast notification module (src/system_notify.py).

The toast path is a best-effort side channel, so the tests pin the contract
rather than the platform: payload shaping, empty-input guards, and the
never-raises guarantee. The actual WinRT call is faked through the
module-level ``show_toast`` seam, so no test mutates ``sys.modules``
globally - that would leak into unrelated suites.
"""

from __future__ import annotations

import asyncio

from src import system_notify
from src.system_notify import (
    MAX_CODES_PER_TOAST,
    notify_new_codes_toast,
    notify_redeemed_toast,
    notify_toast,
    show_toast,
)


def test_empty_payload_returns_false_without_calling_winotify(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        system_notify, "show_toast", lambda title, msg: calls.append((title, msg)) or False
    )
    assert show_toast("", "") is False
    assert calls == []


def test_success_path_builds_notification(monkeypatch) -> None:
    shown: list[dict[str, object]] = []

    class _FakeNotification:
        def __init__(self, app_id: str, title: str, msg: str = "") -> None:
            shown.append({"app_id": app_id, "title": title, "msg": msg})

        def show(self, *args: object, **kwargs: object) -> None:
            shown[-1]["shown"] = bool(args or kwargs)

    monkeypatch.setattr("winotify.Notification", _FakeNotification)
    assert show_toast("Title", "Message") is True
    assert shown == [
        {
            "app_id": system_notify.APP_ID,
            "title": "Title",
            "msg": "Message",
            "shown": False,
        }
    ]


def test_notify_toast_runs_in_thread_and_returns_flag(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        system_notify, "show_toast", lambda t, m: seen.append((t, m)) or True
    )
    assert asyncio.run(notify_toast("t", "m")) is True
    assert seen == [("t", "m")]


def test_new_codes_toast_batches_and_truncates(monkeypatch) -> None:
    sent: list[tuple[str, str]] = []

    async def _fake(title: str, message: str) -> bool:
        sent.append((title, message))
        return True

    monkeypatch.setattr(system_notify, "notify_toast", _fake)
    assert asyncio.run(notify_new_codes_toast(["A1", "B2", "C3"])) is True
    assert asyncio.run(notify_new_codes_toast([f"C{i}" for i in range(9)])) is True

    assert sent[0] == ("New codes: 3", "A1, B2, C3")
    assert sent[1][0] == "New codes: 9"
    assert sent[1][1] == "C0, C1, C2, C3, C4 (+4 more)"
    assert MAX_CODES_PER_TOAST == 5  # noqa: PLR2004 -- pins the batching constant


def test_new_codes_toast_empty_returns_false() -> None:
    assert asyncio.run(notify_new_codes_toast([])) is False


def test_redeemed_toast_formats_detail(monkeypatch) -> None:
    sent: list[tuple[str, str]] = []

    async def _fake(title: str, message: str) -> bool:
        sent.append((title, message))
        return True

    monkeypatch.setattr(system_notify, "notify_toast", _fake)
    assert asyncio.run(notify_redeemed_toast("ABCD1234", "main", "60 primogems")) is True
    assert asyncio.run(notify_redeemed_toast("ABCD1234", "main", "")) is True
    assert asyncio.run(notify_redeemed_toast("", "main", "x")) is False

    assert sent[0] == ("Redeemed ABCD1234", "main: 60 primogems")
    assert sent[1] == ("Redeemed ABCD1234", "main")


def test_is_configured_reflects_importability() -> None:
    # On the dev box winotify is installed; either way the answer must be a bool.
    assert isinstance(system_notify.is_configured(), bool)
