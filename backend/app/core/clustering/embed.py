"""
Text embedding generation using fastembed + BGE-M3.

Generates 1024-dimensional dense embeddings for complaint text.
Used as input to the similarity-based clustering pipeline.
"""

from fastembed import TextEmbedding
import logging
from typing import List

logger = logging.getLogger(__name__)

# ── Lazy singleton ───────────────────────────────────────────────────────────
# The BGE-M3 model is ~600 MB. We load it once and reuse across calls.
_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    """Lazy-load the BGE-M3 embedding model."""
    global _model
    if _model is None:
        logger.info("Loading BGE-M3 embedding model (first call)...")
        _model = TextEmbedding(model_name="BAAI/bge-m3")
        logger.info("BGE-M3 model loaded successfully")
    return _model


def generate_embedding(text: str) -> List[float]:
    """
    Generate a 1024-dim dense embedding for the given text.

    Args:
        text: The complaint text (raw_text or formalized_text).

    Returns:
        A list of 1024 floats representing the embedding vector.
    """
    if not text or not text.strip():
        raise ValueError("Cannot generate embedding for empty text")

    model = _get_model()
    # fastembed returns a generator of numpy arrays
    embeddings = list(model.embed([text]))
    vector = embeddings[0].tolist()

    logger.debug("Generated embedding of dimension %d", len(vector))
    return vector


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a batch of texts efficiently.

    Args:
        texts: List of complaint texts.

    Returns:
        List of 1024-dim embedding vectors.
    """
    if not texts:
        return []

    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]
