"""Story 35.12: Tests for AI Research Pipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.research_pipeline import (
    _compute_hash,
    _extract_text_from_html,
    get_suggested_sources,
)


class TestExtractTextFromHtml:
    def test_extracts_main_content(self):
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <nav>Navigation</nav>
            <main>
                <h1>Insulin Information</h1>
                <p>Humalog onset is 15-30 minutes.</p>
            </main>
            <footer>Footer</footer>
        </body>
        </html>
        """
        result = _extract_text_from_html(html)
        assert "Insulin Information" in result
        assert "Humalog onset" in result
        assert "Navigation" not in result
        assert "Footer" not in result

    def test_strips_scripts_and_styles(self):
        html = """
        <html>
        <body>
            <script>alert('xss')</script>
            <style>.hidden { display: none }</style>
            <p>Real content here.</p>
        </body>
        </html>
        """
        result = _extract_text_from_html(html)
        assert "Real content here" in result
        assert "alert" not in result
        assert "display" not in result

    def test_falls_back_to_body_without_main(self):
        html = "<html><body><p>Just a paragraph.</p></body></html>"
        result = _extract_text_from_html(html)
        assert "Just a paragraph" in result

    def test_truncates_long_content(self):
        html = f"<html><body><p>{'A' * 60000}</p></body></html>"
        result = _extract_text_from_html(html)
        assert len(result) <= 50000


class TestComputeHash:
    def test_consistent_hashing(self):
        h1 = _compute_hash("test content")
        h2 = _compute_hash("test content")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = _compute_hash("content a")
        h2 = _compute_hash("content b")
        assert h1 != h2


class TestGetSuggestedSources:
    @pytest.mark.asyncio
    async def test_suggests_insulin_source(self):
        db = AsyncMock()

        # No existing sources
        existing_result = MagicMock()
        existing_result.all.return_value = []

        # Insulin config: humalog
        insulin_config = MagicMock()
        insulin_config.insulin_type = "humalog"
        insulin_result = MagicMock()
        insulin_result.scalar_one_or_none.return_value = insulin_config

        # No pump info
        pump_result = MagicMock()
        pump_result.scalar_one_or_none.return_value = None

        # No integrations
        integrations_result = MagicMock()
        integrations_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [
            existing_result,
            insulin_result,
            pump_result,
            integrations_result,
        ]

        suggestions = await get_suggested_sources(db, uuid.uuid4())
        assert len(suggestions) >= 1
        assert any(
            "humalog" in s["name"].lower() or "lilly" in s["name"].lower()
            for s in suggestions
        )

    @pytest.mark.asyncio
    async def test_no_suggestions_when_no_config(self):
        db = AsyncMock()

        existing_result = MagicMock()
        existing_result.all.return_value = []

        insulin_result = MagicMock()
        insulin_result.scalar_one_or_none.return_value = None

        pump_result = MagicMock()
        pump_result.scalar_one_or_none.return_value = None

        integrations_result = MagicMock()
        integrations_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [
            existing_result,
            insulin_result,
            pump_result,
            integrations_result,
        ]

        suggestions = await get_suggested_sources(db, uuid.uuid4())
        assert suggestions == []

    @pytest.mark.asyncio
    async def test_skips_already_configured_sources(self):
        db = AsyncMock()

        # Existing sources include the humalog URL
        from src.services.research_pipeline import INSULIN_SOURCES

        humalog_url = INSULIN_SOURCES["humalog"]["url"]
        existing_result = MagicMock()
        existing_result.all.return_value = [(humalog_url,)]

        insulin_config = MagicMock()
        insulin_config.insulin_type = "humalog"
        insulin_result = MagicMock()
        insulin_result.scalar_one_or_none.return_value = insulin_config

        pump_result = MagicMock()
        pump_result.scalar_one_or_none.return_value = None

        integrations_result = MagicMock()
        integrations_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [
            existing_result,
            insulin_result,
            pump_result,
            integrations_result,
        ]

        suggestions = await get_suggested_sources(db, uuid.uuid4())
        # Humalog already configured, should not be suggested
        humalog_suggestions = [
            s
            for s in suggestions
            if "humalog" in s.get("name", "").lower()
            or "lilly" in s.get("name", "").lower()
        ]
        assert len(humalog_suggestions) == 0
