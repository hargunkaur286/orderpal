"""Turns text into vectors with a local embedding model (no API key, no cost).

bge-small-en-v1.5: 384 dimensions, ~130 MB, fast on a laptop CPU. It's a *bi-encoder*: queries
and documents are embedded separately, so document vectors can be computed once and stored.
"""
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings

# bge models were trained with this instruction in front of short search queries (not documents).
# It nudges the query vector toward "passage that answers this" rather than "sentence like this".
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache
def get_model() -> SentenceTransformer:
    """Loaded once per process: loading takes seconds, encoding takes milliseconds."""
    return SentenceTransformer(get_settings().embedding_model)


def embed_documents(texts: list[str]) -> np.ndarray:
    # normalize_embeddings=True -> every vector has length 1, so cosine similarity == dot product.
    return get_model().encode(texts, normalize_embeddings=True, batch_size=32)


def embed_query(text: str) -> np.ndarray:
    return get_model().encode(QUERY_INSTRUCTION + text, normalize_embeddings=True)
