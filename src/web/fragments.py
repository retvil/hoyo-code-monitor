"""HTML fragment renderer for redemption results.

Centralizes the manual HTML-escaping + span construction that was
previously inlined in ``web_ui.py`` redeem routes.
"""

from __future__ import annotations

import html


def render_result_fragment(
    results: list[dict[str, object]],
    ok: bool,
) -> str:
    """Render a styled redemption-result HTML fragment.

    Args:
        results: List of dicts with keys ``account``, ``ok``, ``msg``.
        ok: Overall success (any_success for single-code, failed==0 for all).

    Returns:
        An HTML string with a ``<span>`` carrying the appropriate CSS class,
        ``data-toast`` and ``data-toast-ok`` attributes for the client-side
        toast handler.
    """
    items = [
        f"{r['account']}: {'✓' if r['ok'] else '✗'} {r['msg']}"
        for r in results
    ]
    text = "; ".join(items)
    cls = "redeem-result-ok" if ok else "redeem-result-err"
    return (
        f'<span class="{cls}" '
        f'data-toast="{html.escape(text)}" '
        f'data-toast-ok="{str(ok).lower()}">{html.escape(text)}</span>'
    )


def render_summary_fragment(text: str, ok: bool) -> str:
    """Render a simple single-text redemption summary HTML fragment.

    Used by the redeem-all route where there is no per-account breakdown
    to display inline (only the aggregate "Redeemed: N, failed: M").

    Args:
        text: Pre-formatted summary string (e.g. "Redeemed: 3, failed: 1").
        ok: Overall success flag.

    Returns:
        An HTML string with the appropriate CSS class and data attributes.
    """
    cls = "redeem-result-ok" if ok else "redeem-result-err"
    escaped = html.escape(text)
    return (
        f'<span class="{cls}" '
        f'data-toast="{escaped}" '
        f'data-toast-ok="{str(ok).lower()}">{escaped}</span>'
    )
