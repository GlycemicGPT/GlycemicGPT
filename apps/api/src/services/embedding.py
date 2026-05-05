"""Story 35.9: Embedding service for RAG system.

Generates text embeddings using fastembed (in-process, CPU-only).
The model downloads on first use (~500MB) and caches to disk.
"""

import threading

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Lazy-loaded model instance with thread-safe initialization
_model = None
_model_lock = threading.Lock()

# Default model -- good balance of quality and size, runs on CPU
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"

# Output dimension of the default model. MUST match the pgvector column
# definition in migration 048 (`embedding vector(768)`); a mismatch is
# rejected at INSERT time. Switching DEFAULT_EMBEDDING_MODEL to a model
# with a different dimension is a coordinated schema migration, not a
# config change.
EMBEDDING_DIM = 768


def _get_model():
    """Get or initialize the embedding model (lazy loading)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # Double-check after acquiring lock
                from fastembed import TextEmbedding

                model_name = (
                    getattr(settings, "embedding_model", None)
                    or DEFAULT_EMBEDDING_MODEL
                )
                logger.info("Loading embedding model", model=model_name)
                _model = TextEmbedding(model_name=model_name)
                logger.info("Embedding model loaded", model=model_name)
    return _model


def _assert_dim(vec: list[float]) -> list[float]:
    """Validate the model produced a vector at the expected dimension.

    Catches silent model swaps that would otherwise reach pgvector's
    `vector(768)` column and fail at INSERT time with a less actionable
    error. A mismatch here means the DEFAULT_EMBEDDING_MODEL changed
    without a coordinated migration of the column type."""
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(vec)}, expected "
            f"{EMBEDDING_DIM}. Switching DEFAULT_EMBEDDING_MODEL requires "
            "a coordinated migration of the knowledge_chunks.embedding "
            "column type."
        )
    return vec


def embed_text(text: str) -> list[float]:
    """Embed a single text string into a vector.

    Args:
        text: Text to embed (should be under ~512 tokens for best results).

    Returns:
        List of floats representing the embedding vector (EMBEDDING_DIM
        dimensions).
    """
    model = _get_model()
    embeddings = list(model.embed([text]))
    return _assert_dim(embeddings[0].tolist())


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in a batch.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors, each at EMBEDDING_DIM dimensions.
    """
    if not texts:
        return []
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [_assert_dim(e.tolist()) for e in embeddings]


def preload_model() -> None:
    """Pre-download and load the embedding model.

    Called during API startup to ensure the model is ready
    before the first request. Downloads ~500MB on first run.
    """
    _get_model()
    logger.info("Embedding model preloaded and ready")
