"""Text embedders: Vertex for production, a deterministic hashing one for offline tests."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, Protocol

import numpy as np
from google import genai
from google.genai import types

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
_BATCH = 100  # Vertex text-embedding limit is well above this; keep requests small.


class Embedder(Protocol):
    async def embed(self, texts: list[str], task_type: TaskType) -> np.ndarray:
        """Return a float32 array of shape (len(texts), dim); rows need not be normalised."""
        ...


class VertexEmbedder:
    """Embeds with google-genai `embed_content` on Vertex (ADC)."""

    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(self, texts: list[str], task_type: TaskType) -> np.ndarray:
        rows: list[list[float]] = []
        for start in range(0, len(texts), _BATCH):
            response = await self._client.aio.models.embed_content(
                model=self._model,
                contents=list(texts[start : start + _BATCH]),
                config=types.EmbedContentConfig(task_type=task_type),
            )
            for embedding in response.embeddings or []:
                rows.append(list(embedding.values or []))
        if len(rows) != len(texts):
            raise RuntimeError(f"expected {len(texts)} embeddings, got {len(rows)}")
        return np.asarray(rows, dtype=np.float32)


_WORD = re.compile(r"\w+", re.UNICODE)


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (no network). Rows are L2-normalised."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.calls: list[tuple[int, str]] = []

    async def embed(self, texts: list[str], task_type: TaskType) -> np.ndarray:
        self.calls.append((len(texts), task_type))
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                digest = hashlib.sha256(word.encode("utf-8")).digest()
                out[row, int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms
