"""Tests for src.web.fragments (HTML result renderer)."""

from src.web.fragments import render_result_fragment, render_summary_fragment


class TestRenderResultFragment:
    """render_result_fragment escapes HTML and uses correct CSS class."""

    def test_single_success(self) -> None:
        results = [{"account": "main", "ok": True, "msg": "OK"}]
        html = render_result_fragment(results, True)
        assert 'class="redeem-result-ok"' in html
        assert 'data-toast-ok="true"' in html
        assert "main: ✓ OK" in html

    def test_single_failure(self) -> None:
        results = [{"account": "main", "ok": False, "msg": "expired"}]
        html = render_result_fragment(results, False)
        assert 'class="redeem-result-err"' in html
        assert 'data-toast-ok="false"' in html
        assert "main: ✗ expired" in html

    def test_html_injection_is_escaped(self) -> None:
        results = [{"account": "<script>alert(1)</script>", "ok": True, "msg": "OK"}]
        html = render_result_fragment(results, True)
        # The raw script tag must not appear
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_multiple_accounts_mixed(self) -> None:
        results = [
            {"account": "acc1", "ok": True, "msg": "OK"},
            {"account": "acc2", "ok": False, "msg": "fail"},
        ]
        html = render_result_fragment(results, True)  # any_success is True
        assert 'class="redeem-result-ok"' in html
        assert "acc1: ✓ OK" in html
        assert "acc2: ✗ fail" in html
        # Both results joined by "; "
        assert "acc1: ✓ OK; acc2: ✗ fail" in html

    def test_msg_with_html_special_chars(self) -> None:
        results = [{"account": "a", "ok": True, "msg": "a&b<c>"}]
        html = render_result_fragment(results, True)
        assert "a&b<c>" not in html  # raw not present
        assert "&amp;" in html or "a&amp;b" in html


class TestRenderSummaryFragment:
    """render_summary_fragment renders a simple aggregate result."""

    def test_success(self) -> None:
        html = render_summary_fragment("Redeemed: 3, failed: 0", True)
        assert 'class="redeem-result-ok"' in html
        assert "Redeemed: 3" in html

    def test_failure(self) -> None:
        html = render_summary_fragment("Redeemed: 0, failed: 1", False)
        assert 'class="redeem-result-err"' in html

    def test_html_injection_escaped(self) -> None:
        html = render_summary_fragment("<b>bold</b>", True)
        assert "<b>" not in html
        assert "&lt;b&gt;" in html
