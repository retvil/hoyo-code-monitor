"""RedemptionService — single source of truth for the claim → log → cookie-state write path.

Previously this logic was duplicated in three places:
  1. ``scheduler._redeem_code_for_account`` (background auto-redeem)
  2. ``web_ui.redeem_single_code`` (manual single-code redeem)
  3. ``web_ui.redeem_all_codes`` (manual redeem-all)

This service centralises the logic so all three call sites use the same
code path, with identical error handling, logging, and notification.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from src.constants import GAME_CONF
from src.redeemer import RedemptionResult

logger = logging.getLogger(__name__)


class RedemptionService:
    """Owns the claim → log → cookie-state write path.

    Instances are created per web-request cycle (cheap, stateless) or
    reused by the scheduler across its lifetime.
    """

    def __init__(
        self,
        storage: Any,
        redeemer: Any,
        notify_func: Any = None,
        toast_func: Any = None,
    ) -> None:
        """
        Args:
            storage: A ``Storage`` instance.
            redeemer: A ``Redeemer`` instance.
            notify_func: Optional async callable ``fn(storage, code, account_name, reward)``
                used for external notifications (Telegram, etc.).
            toast_func: Optional async callable ``fn(code, account_name, reward)``
                used for local Windows toasts.
        """
        self.storage = storage
        self.redeemer = redeemer
        self._notify_func = notify_func
        self._toast_func = toast_func

    async def redeem_code_for_account(
        self,
        code: str,
        acc: dict[str, Any],
    ) -> bool:
        """Redeem a single code for one account.

        Mirrors the exact logic that was in ``scheduler._redeem_code_for_account``.
        Returns True if the code was successfully claimed (including "already used"
        retcodes -2017/-2018 which are treated as non-errors).
        """
        from src.notify import notify_redeemed
        from src.system_notify import notify_redeemed_toast

        acc_name = acc["name"]
        acc_game = acc.get("game") or "genshin"
        gconf = GAME_CONF.get(acc_game, GAME_CONF["genshin"])

        acc_cookies = self.storage.load_account_cookies(acc_name)
        if not acc_cookies:
            logger.warning("No cookies saved for account %s; skipping redemption", acc_name)
            return False

        res: RedemptionResult = await self.redeemer.redeem_code(
            code=code,
            cookies=acc_cookies,
            uid=acc["uid"],
            region=acc["region"],
            game_biz=acc.get("game_biz") or gconf["game_biz"],
            lang=acc.get("lang", "en-us"),
            s_lang_key=acc.get("s_lang_key", "en-us"),
            game=acc_game,
        )

        retcode = res.raw_response.get("retcode")
        claimed = res.success or retcode in (-2017, -2018)

        # Cookie-expired path
        if retcode in (10001, -100):
            self.storage.set_account_cookie_state(acc_name, "expired")
            logger.info("Cookie expired for account %s (retcode %s)", acc_name, retcode)

        # Preserve existing reward text when this account already claimed
        existing = self.storage.get_code(code, game=acc_game)
        new_reward = res.reward if res.success else (existing or {}).get("reward")

        self.storage.update_code_redemption(
            code=code,
            redeemed=claimed,
            reward=new_reward,
            game=acc_game,
        )
        self.storage.add_redemption_log(
            code=code,
            account_id=acc.get("id", acc_name),
            status="success" if claimed else "failed",
            reward=res.reward if res.success else None,
            error_message=None if claimed else res.message,
        )

        if claimed:
            self.storage.set_account_cookie_state(acc_name, "ok")
            reward_text = res.reward or "claimed"
            if self._notify_func:
                with contextlib.suppress(Exception):
                    await self._notify_func(self.storage, code, acc_name, reward_text)
            else:
                with contextlib.suppress(Exception):
                    await notify_redeemed(self.storage, code, acc_name, reward_text)
            if self._toast_func:
                with contextlib.suppress(Exception):
                    await self._toast_func(code, acc_name, reward_text)
            else:
                with contextlib.suppress(Exception):
                    await notify_redeemed_toast(code, acc_name, reward_text)

        return claimed
