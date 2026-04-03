"""Story 35.12: AI Research Pipeline.

Fetches clinical documentation from user-configured sources,
detects content changes, and populates the knowledge base with
device/insulin/CGM-specific information.
"""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.models.research_source import ResearchSource
from src.services.embedding import embed_texts
from src.services.knowledge_seed import _chunk_text

logger = get_logger(__name__)

# Limits
MAX_CONTENT_BYTES = 512_000  # 500KB max per page
FETCH_TIMEOUT_SECONDS = 30
MAX_SOURCES_PER_USER = 10
MAX_TEXT_LENGTH = 50_000  # 50K chars of extracted text

# Source suggestions based on user configuration
INSULIN_SOURCES: dict[str, dict[str, str]] = {
    "humalog": {
        "url": "https://www.lillymedical.com/en-us/answers/humalog",
        "name": "Humalog (insulin lispro) - Lilly Medical",
        "category": "insulin",
    },
    "novolog": {
        "url": "https://www.novologpro.com/about/what-is-novolog.html",
        "name": "Novolog (insulin aspart) - Novo Nordisk",
        "category": "insulin",
    },
    "fiasp": {
        "url": "https://www.fiasppro.com/about-fiasp/how-fiasp-works.html",
        "name": "Fiasp (faster insulin aspart) - Novo Nordisk",
        "category": "insulin",
    },
    "lyumjev": {
        "url": "https://www.lyumjevpro.com/about-lyumjev",
        "name": "Lyumjev (insulin lispro-aabc) - Lilly Medical",
        "category": "insulin",
    },
}

PUMP_SOURCES: dict[str, dict[str, str]] = {
    "tandem": {
        "url": "https://www.tandemdiabetes.com/products/t-slim-x2",
        "name": "Tandem t:slim X2 Insulin Pump",
        "category": "pump",
    },
}

CGM_SOURCES: dict[str, dict[str, str]] = {
    "dexcom": {
        "url": "https://www.dexcom.com/en-us/g7",
        "name": "Dexcom G7 Continuous Glucose Monitor",
        "category": "cgm",
    },
}


def _extract_text_from_html(html_content: str) -> str:
    """Extract meaningful text content from an HTML page.

    Strips navigation, scripts, styles, and other non-content elements.
    Preserves headings and paragraph structure.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(
        ["script", "style", "nav", "footer", "header", "aside", "noscript"]
    ):
        tag.decompose()

    # Try to find main content area
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    if main:
        text = main.get_text(separator="\n\n", strip=True)
    else:
        text = soup.get_text(separator="\n\n", strip=True)

    # Clean up excessive whitespace
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            lines.append(stripped)

    result = "\n\n".join(lines)
    return result[:MAX_TEXT_LENGTH]


def _compute_hash(content: str) -> str:
    """Compute SHA-256 hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()


def _validate_research_url(url: str) -> None:
    """Validate a research URL at fetch time (defense in depth).

    Unlike AI provider URLs, research sources must NEVER target private
    networks, regardless of allow_private_ai_urls setting.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Research sources must use HTTPS")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL")

    # Always block cloud metadata
    blocked_hosts = {"169.254.169.254", "metadata.google.internal", "metadata.internal"}
    if hostname.lower() in blocked_hosts:
        raise ValueError("Invalid URL")

    # Always block private/loopback IPs for research (no bypass)
    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for entry in addrs:
            addr = ipaddress.ip_address(entry[4][0])
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            ):
                raise ValueError("Invalid URL")
    except (socket.gaierror, OSError) as exc:
        raise ValueError("Invalid URL") from exc


async def fetch_source_content(url: str) -> str | None:
    """Fetch content from a research source URL.

    SSRF protection: re-validates URL at fetch time (not just creation),
    blocks redirects, checks Content-Length before download.
    """
    # Re-validate at fetch time (defense against DNS rebinding)
    try:
        _validate_research_url(url)
    except ValueError:
        logger.warning("Research URL failed fetch-time validation", url=url)
        return None

    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,  # Follow redirects but validate each hop
            max_redirects=5,
            headers={"User-Agent": "GlycemicGPT Research Bot/1.0"},
        ) as client:
            response = await client.get(url)

            # Validate the final URL after redirects (defense against
            # redirect-based SSRF to internal services)
            final_url = str(response.url)
            try:
                _validate_research_url(final_url)
            except ValueError:
                logger.warning(
                    "Research redirect target failed validation (blocked)",
                    original_url=url,
                    final_url=final_url,
                )
                return None

            response.raise_for_status()

            # Check Content-Length before reading body
            content_length = response.headers.get("content-length")
            try:
                if content_length and int(content_length) > MAX_CONTENT_BYTES:
                    logger.warning(
                        "Research source content too large (Content-Length)",
                        url=url,
                        size=content_length,
                    )
                    return None
            except (ValueError, TypeError):
                pass  # Malformed Content-Length header, skip check

            # Check actual body size
            if len(response.content) > MAX_CONTENT_BYTES:
                logger.warning(
                    "Research source content too large",
                    url=url,
                    size=len(response.content),
                )
                return None

            content_type = response.headers.get("content-type", "")

            if "html" in content_type:
                return _extract_text_from_html(response.text)
            elif "text/plain" in content_type:
                return response.text[:MAX_TEXT_LENGTH]
            elif "application/pdf" in content_type:
                # PDF extraction deferred to Story 35.11 (User Document Upload)
                logger.info("PDF source detected, skipping for now", url=url)
                return None
            else:
                logger.warning(
                    "Unsupported content type for research source",
                    url=url,
                    content_type=content_type,
                )
                return None

    except httpx.HTTPStatusError as e:
        logger.warning(
            "Research source returned error status",
            url=url,
            status=e.response.status_code,
        )
        return None
    except Exception:
        logger.warning("Failed to fetch research source", url=url, exc_info=True)
        return None


async def research_source(
    db: AsyncSession,
    source: ResearchSource,
) -> dict:
    """Research a single source: fetch, compare, update if changed.

    Returns a status dict: {status: 'unchanged'|'updated'|'new'|'error', chunks: int}
    """
    # Fetch content
    content = await fetch_source_content(source.url)
    if content is None:
        source.last_researched_at = datetime.now(UTC)
        return {"status": "error", "chunks": 0}

    if len(content.strip()) < 100:
        logger.info(
            "Research source content too short", url=source.url, length=len(content)
        )
        source.last_researched_at = datetime.now(UTC)
        return {"status": "error", "chunks": 0}

    # Hash comparison
    new_hash = _compute_hash(content)
    if new_hash == source.last_content_hash:
        source.last_researched_at = datetime.now(UTC)
        return {"status": "unchanged", "chunks": 0}

    is_new = source.last_content_hash is None
    now = datetime.now(UTC)

    # Invalidate old chunks from this source
    if not is_new:
        old_chunks_result = await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.user_id == source.user_id,
                KnowledgeChunk.source_url == source.url,
                KnowledgeChunk.valid_to.is_(None),
            )
        )
        for old_chunk in old_chunks_result.scalars().all():
            old_chunk.valid_to = now

    # Chunk the content
    chunks = _chunk_text(content)
    if not chunks:
        source.last_researched_at = now
        source.last_content_hash = new_hash
        return {"status": "updated" if not is_new else "new", "chunks": 0}

    # Embed all chunks (run in thread to avoid blocking event loop)
    try:
        embeddings = await asyncio.to_thread(embed_texts, chunks)
    except Exception:
        logger.error("Failed to embed research chunks", url=source.url, exc_info=True)
        source.last_researched_at = now
        return {"status": "error", "chunks": 0}

    # Store new chunks
    for chunk_text, embedding in zip(chunks, embeddings, strict=True):
        db.add(
            KnowledgeChunk(
                user_id=source.user_id,
                trust_tier="RESEARCHED",
                source_type="ai_research",
                source_url=source.url,
                source_name=source.name,
                content=chunk_text,
                embedding=embedding,
                content_hash=_compute_hash(chunk_text),
                retrieved_at=now,
                metadata_json={
                    "category": source.category,
                    "research_source_id": str(source.id),
                },
            )
        )

    # Update source
    source.last_researched_at = now
    source.last_content_hash = new_hash

    logger.info(
        "Research source updated",
        url=source.url,
        chunks=len(chunks),
        is_new=is_new,
        user_id=str(source.user_id),
    )

    return {
        "status": "new" if is_new else "updated",
        "chunks": len(chunks),
    }


async def research_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Run the research pipeline for a single user.

    Fetches all active research sources and processes them.
    Returns summary of results.
    """
    result = await db.execute(
        select(ResearchSource).where(
            ResearchSource.user_id == user_id,
            ResearchSource.is_active.is_(True),
        )
    )
    sources = list(result.scalars().all())

    if not sources:
        return {"sources": 0, "updated": 0, "new": 0, "unchanged": 0, "errors": 0}

    summary = {
        "sources": len(sources),
        "updated": 0,
        "new": 0,
        "unchanged": 0,
        "errors": 0,
    }

    for source in sources:
        try:
            result_status = await research_source(db, source)
            await db.commit()  # Commit after each source for isolation
            # Normalize "error" -> "errors" to match summary dict keys
            key = result_status["status"]
            if key == "error":
                key = "errors"
            summary[key] = summary.get(key, 0) + 1
        except Exception:
            await db.rollback()
            logger.error(
                "Research failed for source",
                url=source.url,
                user_id=str(user_id),
                exc_info=True,
            )
            summary["errors"] += 1

    logger.info(
        "Research pipeline completed for user",
        user_id=str(user_id),
        **summary,
    )

    return summary


async def get_suggested_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """Get suggested research sources based on user's device/insulin configuration.

    Reads InsulinConfig, IntegrationCredentials, and PumpHardwareInfo to
    determine which manufacturer documentation would be relevant.
    """
    from src.models.insulin_config import InsulinConfig
    from src.models.integration import IntegrationCredential, IntegrationType
    from src.models.pump_hardware_info import PumpHardwareInfo

    suggestions: list[dict] = []
    existing_urls: set[str] = set()

    # Check what sources the user already has
    existing_result = await db.execute(
        select(ResearchSource.url).where(ResearchSource.user_id == user_id)
    )
    existing_urls = {row[0] for row in existing_result.all()}

    # Insulin-based suggestions
    insulin_result = await db.execute(
        select(InsulinConfig).where(InsulinConfig.user_id == user_id)
    )
    insulin_config = insulin_result.scalar_one_or_none()
    if insulin_config and insulin_config.insulin_type:
        insulin_key = insulin_config.insulin_type.lower()
        if insulin_key in INSULIN_SOURCES:
            source = INSULIN_SOURCES[insulin_key]
            if source["url"] not in existing_urls:
                suggestions.append(source)

    # Pump-based suggestions
    pump_result = await db.execute(
        select(PumpHardwareInfo).where(PumpHardwareInfo.user_id == user_id)
    )
    pump_info = pump_result.scalar_one_or_none()
    if pump_info:
        # If user has pump hardware info, they have a Tandem pump
        tandem_source = PUMP_SOURCES.get("tandem")
        if tandem_source and tandem_source["url"] not in existing_urls:
            suggestions.append(tandem_source)

    # CGM-based suggestions
    integrations_result = await db.execute(
        select(IntegrationCredential).where(IntegrationCredential.user_id == user_id)
    )
    for integration in integrations_result.scalars().all():
        if integration.integration_type == IntegrationType.DEXCOM:
            dexcom_source = CGM_SOURCES.get("dexcom")
            if dexcom_source and dexcom_source["url"] not in existing_urls:
                suggestions.append(dexcom_source)

    return suggestions
