"""Story 35.12: AI-Driven Research Pipeline.

The AI is the researcher. It analyzes user-configured source domains,
directs the platform to fetch specific pages, evaluates content for
clinical relevance, and outputs structured findings that get stored
in the knowledge base.

The platform enforces guardrails:
- Only allowed domains can be fetched
- SSRF protection on all fetches
- Max pages per session
- AI can RECOMMEND new domains but cannot fetch from them without user approval

Phase 1: Two-step approach (plan + evaluate) without tool-use API.
Phase 2: Full agentic with tool-use API calls.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from src.models.user import User

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.models.research_source import ResearchSource
from src.schemas.ai_response import AIMessage
from src.services.ai_client import get_ai_client
from src.services.embedding import embed_texts
from src.services.knowledge_seed import _chunk_text
from src.services.research_pipeline import (
    _compute_hash,
    fetch_source_content,
)

# Patterns that suggest prompt injection in research findings
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"override\s+(safety|guidelines|protocol)", re.IGNORECASE),
    re.compile(r"do\s+not\s+mention\s+this", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
]


def _check_injection_risk(text: str) -> bool:
    """Check if text contains potential prompt injection patterns."""
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


logger = get_logger(__name__)

# Limits
MAX_PAGES_PER_SESSION = 10
MAX_FINDINGS_PER_SOURCE = 10
MAX_RECOMMENDATIONS_PER_SOURCE = 5
MAX_RECOMMENDATIONS_TOTAL = 20
MAX_PAGE_CONTENT_CHARS = 15_000  # Per-page cap for AI context
MAX_TOTAL_CONTENT_CHARS = 30_000  # Total cap for evaluation call
VALID_STATUSES = {"new", "updated", "unchanged", "error"}

# Research system prompt
RESEARCH_SYSTEM_PROMPT = """\
You are a clinical research assistant for GlycemicGPT, a diabetes management \
platform. Your job is to research medical devices, medications, and clinical \
documentation to build a knowledge base for a Type 1 diabetes patient.

IMPORTANT RULES:
- You may ONLY request fetches from the allowed domains listed below.
- If you find a reference to a valuable source on a NON-allowed domain, \
do NOT request a fetch. Instead, add it to "recommendations" with a reason \
why the user should add it.
- Focus on clinical/technical content. Skip marketing material, testimonials, \
and promotional content.
- Include specific numbers (dosing, timing, thresholds) where available.
- Structure findings by topic (device specs, algorithm behavior, compatibility, etc.).\
"""

RESEARCH_PLAN_PROMPT = """\
I need you to research: {topic}
Category: {category}

Allowed domains (you may ONLY request pages from these):
{allowed_domains}

The starting URL is: {start_url}

Current knowledge base for this source:
{existing_knowledge}

STEP 1: I will fetch the starting page for you. Here is its content:

---
{page_content}
---

Based on this content, respond with a JSON object:
{{
  "pages_to_fetch": [
    {{"url": "https://...", "reason": "Contains Control-IQ algorithm details"}}
  ],
  "findings_from_this_page": [
    {{
      "topic": "Device Overview",
      "content": "The t:slim X2 is... [structured clinical content]",
      "source_url": "{start_url}"
    }}
  ],
  "recommendations": [
    {{
      "domain": "dexcom.com",
      "url": "https://www.dexcom.com/compatibility",
      "reason": "Found reference to Dexcom compatibility info relevant to this pump"
    }}
  ]
}}

Rules for pages_to_fetch:
- ONLY URLs within the allowed domains: {allowed_domains_list}
- Maximum {max_pages} additional pages
- Choose pages with clinical/technical content, not marketing pages

Rules for findings:
- Each finding should be a self-contained piece of clinical knowledge
- Include specific numbers, thresholds, and technical details
- Do NOT include marketing copy or promotional language

Rules for recommendations:
- Only for domains NOT in the allowed list
- Explain why this source would be valuable
- The user will decide whether to approve it\
"""

EVALUATE_PROMPT = """\
I fetched {page_count} additional pages for research on: {topic}

Here are the contents:

{pages_content}

Based on ALL the content (including what you already found), provide your \
final structured findings as a JSON object:
{{
  "findings": [
    {{
      "topic": "Topic Name",
      "content": "Structured clinical content...",
      "source_url": "https://..."
    }}
  ],
  "recommendations": [
    {{
      "domain": "example.com",
      "url": "https://...",
      "reason": "Why this source is valuable"
    }}
  ],
  "summary": "Brief summary of what was researched and key findings"
}}

Focus on clinical accuracy. Structure findings as reference material \
that a diabetes management AI will use to help patients.\
"""


def _get_allowed_domains(sources: list[ResearchSource]) -> set[str]:
    """Extract allowed domains from user's research sources."""
    domains = set()
    for source in sources:
        parsed = urlparse(source.url)
        if parsed.hostname:
            domains.add(parsed.hostname.lower())
    return domains


def _is_url_in_allowed_domains(url: str, allowed_domains: set[str]) -> bool:
    """Check if a URL is within the user's allowed domains.

    Also rejects non-HTTPS URLs and URLs with embedded credentials.
    """
    parsed = urlparse(url)
    # Must be HTTPS
    if parsed.scheme != "https":
        return False
    # Reject URLs with embedded credentials (userinfo)
    if parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower()
    return hostname in allowed_domains


def _parse_ai_json(text: str) -> dict | None:
    """Extract JSON from AI response text (handles markdown code blocks)."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    # Try finding JSON object in text
    for i, char in enumerate(text):
        if char == "{":
            # Find matching closing brace
            depth = 0
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            break
            break

    return None


async def ai_research_source(
    db: AsyncSession,
    user: User,
    source: ResearchSource,
    all_sources: list[ResearchSource],
) -> dict:
    """AI-driven research for a single source.

    The AI directs the research:
    1. Platform fetches the starting page
    2. AI evaluates content, identifies links to follow
    3. Platform fetches additional pages (within allowed domains only)
    4. AI produces structured findings
    5. Platform stores findings in knowledge base

    Returns: {status, chunks, recommendations, pages_fetched}
    """
    now = datetime.now(UTC)
    allowed_domains = _get_allowed_domains(all_sources)

    # Get the user's AI client
    try:
        ai_client = await get_ai_client(user, db)
    except Exception:
        logger.warning(
            "No AI provider configured for research",
            user_id=str(source.user_id),
        )
        return {
            "status": "error",
            "chunks": 0,
            "recommendations": [],
            "pages_fetched": 0,
        }

    # Step 1: Fetch the starting page
    start_content = await fetch_source_content(source.url)
    if not start_content or len(start_content.strip()) < 100:
        source.last_researched_at = now
        return {
            "status": "error",
            "chunks": 0,
            "recommendations": [],
            "pages_fetched": 1,
        }

    # Get existing knowledge summary for this source
    existing_result = await db.execute(
        select(KnowledgeChunk.source_name, KnowledgeChunk.content).where(
            KnowledgeChunk.user_id == source.user_id,
            KnowledgeChunk.source_url == source.url,
            KnowledgeChunk.valid_to.is_(None),
        )
    )
    existing_chunks = existing_result.all()
    existing_summary = "No existing knowledge for this source."
    if existing_chunks:
        existing_summary = "\n".join(
            f"- {row[0]}: {row[1][:200]}..." for row in existing_chunks[:5]
        )

    # Step 2: Ask AI to evaluate starting page and plan next fetches
    plan_prompt = RESEARCH_PLAN_PROMPT.format(
        topic=source.name,
        category=source.category or "general",
        allowed_domains="\n".join(f"- {d}" for d in sorted(allowed_domains)),
        allowed_domains_list=", ".join(sorted(allowed_domains)),
        start_url=source.url,
        existing_knowledge=existing_summary,
        page_content=start_content[:MAX_PAGE_CONTENT_CHARS],
        max_pages=MAX_PAGES_PER_SESSION,
    )

    try:
        plan_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=plan_prompt)],
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            max_tokens=4096,
        )
    except Exception:
        logger.error(
            "AI research plan generation failed", url=source.url, exc_info=True
        )
        source.last_researched_at = now
        return {
            "status": "error",
            "chunks": 0,
            "recommendations": [],
            "pages_fetched": 1,
        }

    plan = _parse_ai_json(plan_response.content)
    if not plan:
        logger.warning("AI returned unparseable research plan", url=source.url)
        source.last_researched_at = now
        return {
            "status": "error",
            "chunks": 0,
            "recommendations": [],
            "pages_fetched": 1,
        }

    # Collect findings from the first page
    all_findings = plan.get("findings_from_this_page", [])
    recommendations = plan.get("recommendations", [])[:MAX_RECOMMENDATIONS_PER_SOURCE]
    pages_fetched = 1

    # Step 3: Fetch additional pages the AI requested (within allowed domains only)
    pages_to_fetch = plan.get("pages_to_fetch", [])
    fetched_pages: list[dict] = []

    for page_req in pages_to_fetch[:MAX_PAGES_PER_SESSION]:
        url = page_req.get("url", "")
        if not url:
            continue

        # GUARDRAIL: Only fetch from allowed domains
        if not _is_url_in_allowed_domains(url, allowed_domains):
            logger.info(
                "AI requested page outside allowed domains (blocked)",
                url=url,
                allowed=sorted(allowed_domains),
            )
            continue

        content = await fetch_source_content(url)
        pages_fetched += 1
        if content and len(content.strip()) >= 100:
            fetched_pages.append(
                {
                    "url": url,
                    "reason": page_req.get("reason", ""),
                    "content": content[:MAX_PAGE_CONTENT_CHARS],
                }
            )

    # Step 4: If we fetched additional pages, ask AI to evaluate all of them
    if fetched_pages:
        pages_content = ""
        for i, page in enumerate(fetched_pages, 1):
            pages_content += f"\n--- Page {i}: {page['url']} ---\n"
            pages_content += f"Reason fetched: {page['reason']}\n\n"
            pages_content += page["content"]
            pages_content += "\n"

        eval_prompt = EVALUATE_PROMPT.format(
            topic=source.name,
            page_count=len(fetched_pages),
            pages_content=pages_content[:MAX_TOTAL_CONTENT_CHARS],
        )

        try:
            eval_response = await ai_client.generate(
                messages=[
                    AIMessage(role="user", content=plan_prompt),
                    AIMessage(role="assistant", content=plan_response.content),
                    AIMessage(role="user", content=eval_prompt),
                ],
                system_prompt=RESEARCH_SYSTEM_PROMPT,
                max_tokens=4096,
            )

            eval_result = _parse_ai_json(eval_response.content)
            if eval_result:
                all_findings = eval_result.get("findings", all_findings)
                recommendations.extend(eval_result.get("recommendations", []))
        except Exception:
            logger.error("AI research evaluation failed", url=source.url, exc_info=True)

    # Step 5: Store findings in knowledge base
    if not all_findings:
        source.last_researched_at = now
        return {
            "status": "new" if not existing_chunks else "unchanged",
            "chunks": 0,
            "recommendations": recommendations,
            "pages_fetched": pages_fetched,
        }

    # Process findings into chunks (invalidation happens AFTER embedding succeeds)
    all_texts = []
    all_metadata = []
    for finding in all_findings[:MAX_FINDINGS_PER_SOURCE]:
        topic = finding.get("topic", "Research Finding")
        content = finding.get("content", "")
        finding_url = finding.get("source_url", source.url)

        if not content or len(content.strip()) < 50:
            continue

        # Prefix with topic for better retrieval
        full_text = f"## {topic}\n\n{content}"
        chunks = _chunk_text(full_text)

        for chunk in chunks:
            all_texts.append(chunk)
            all_metadata.append(
                {
                    "topic": topic,
                    "source_url": finding_url,
                    "category": source.category,
                    "research_source_id": str(source.id),
                }
            )

    if not all_texts:
        source.last_researched_at = now
        source.last_content_hash = _compute_hash(str(all_findings))
        return {
            "status": "new" if not existing_chunks else "updated",
            "chunks": 0,
            "recommendations": recommendations,
            "pages_fetched": pages_fetched,
        }

    # Embed all findings
    try:
        embeddings = await asyncio.to_thread(embed_texts, all_texts)
    except Exception:
        logger.error("Failed to embed research findings", url=source.url, exc_info=True)
        source.last_researched_at = now
        return {
            "status": "error",
            "chunks": 0,
            "recommendations": recommendations,
            "pages_fetched": pages_fetched,
        }

    # Invalidate old chunks only AFTER new embeddings are ready
    # (prevents leaving source with no active knowledge on embedding failure)
    if existing_chunks:
        old_result = await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.user_id == source.user_id,
                KnowledgeChunk.source_url == source.url,
                KnowledgeChunk.valid_to.is_(None),
            )
        )
        for old_chunk in old_result.scalars().all():
            old_chunk.valid_to = now

    # Store chunks (with injection risk scanning)
    for text, embedding, metadata in zip(
        all_texts, embeddings, all_metadata, strict=True
    ):
        # Validate source_url is within allowed domains (AI controls this field)
        finding_url = metadata["source_url"]
        if not _is_url_in_allowed_domains(finding_url, allowed_domains):
            finding_url = source.url  # Fall back to source URL

        db.add(
            KnowledgeChunk(
                user_id=source.user_id,
                trust_tier=KnowledgeChunk.TIER_RESEARCHED,
                source_type="ai_research",
                source_url=finding_url,
                source_name=source.name,
                content=text,
                embedding=embedding,
                content_hash=_compute_hash(text),
                retrieved_at=now,
                metadata_json=metadata,
                injection_risk=_check_injection_risk(text),
            )
        )

    source.last_researched_at = now
    source.last_content_hash = _compute_hash(str(all_findings))

    logger.info(
        "AI research completed for source",
        url=source.url,
        chunks=len(all_texts),
        pages_fetched=pages_fetched,
        recommendations=len(recommendations),
        user_id=str(source.user_id),
    )

    return {
        "status": "new" if not existing_chunks else "updated",
        "chunks": len(all_texts),
        "recommendations": recommendations,
        "pages_fetched": pages_fetched,
    }


async def ai_research_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Run AI-driven research for a single user.

    The AI evaluates each source, follows links within allowed domains,
    and produces structured clinical knowledge.
    """
    from src.models.user import User

    # Get user object (needed for AI client)
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return {
            "sources": 0,
            "updated": 0,
            "new": 0,
            "unchanged": 0,
            "errors": 0,
            "recommendations": [],
        }

    # Get all active sources
    sources_result = await db.execute(
        select(ResearchSource).where(
            ResearchSource.user_id == user_id,
            ResearchSource.is_active.is_(True),
        )
    )
    sources = list(sources_result.scalars().all())

    if not sources:
        return {
            "sources": 0,
            "updated": 0,
            "new": 0,
            "unchanged": 0,
            "errors": 0,
            "recommendations": [],
        }

    summary = {
        "sources": len(sources),
        "updated": 0,
        "new": 0,
        "unchanged": 0,
        "errors": 0,
        "total_chunks": 0,
        "total_pages": 0,
        "recommendations": [],
    }

    for source in sources:
        try:
            result = await ai_research_source(db, user, source, sources)
            await db.commit()

            key = result.get("status", "error")
            if key not in VALID_STATUSES:
                key = "error"
            if key == "error":
                key = "errors"
            summary[key] = summary.get(key, 0) + 1
            summary["total_chunks"] += result.get("chunks", 0)
            summary["total_pages"] += result.get("pages_fetched", 0)
            new_recs = result.get("recommendations", [])
            remaining = MAX_RECOMMENDATIONS_TOTAL - len(summary["recommendations"])
            summary["recommendations"].extend(new_recs[:remaining])
        except Exception:
            await db.rollback()
            logger.error(
                "AI research failed for source",
                url=source.url,
                user_id=str(user_id),
                exc_info=True,
            )
            summary["errors"] += 1

    logger.info(
        "AI research pipeline completed for user",
        user_id=str(user_id),
        **{k: v for k, v in summary.items() if k != "recommendations"},
        recommendation_count=len(summary["recommendations"]),
    )

    return summary
