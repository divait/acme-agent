"""FAQ loader: splits `knowledge/faq_{lang}.md` on `## ` headings into chunks (ADR-007)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

_ID_COMMENT = re.compile(r"^<!--\s*id:\s*([a-z0-9-]+)\s*-->$")
_LANG_FROM_NAME = re.compile(r"^faq_([a-z]{2})\.md$")


class FaqChunk(BaseModel):
    id: str
    language: str
    title: str
    text: str
    source: str  # e.g. "faq_es.md#pay-rider"


def load_faq(paths: Iterable[Path]) -> list[FaqChunk]:
    """Read FAQ files; the language comes from the filename (`faq_es.md` -> `es`)."""
    chunks: list[FaqChunk] = []
    for path in paths:
        match = _LANG_FROM_NAME.match(path.name)
        if not match:
            raise ValueError(f"FAQ file name must look like faq_<lang>.md: {path.name}")
        language = match.group(1)
        raw = path.read_text(encoding="utf-8")
        for part in re.split(r"^## ", raw, flags=re.M)[1:]:
            lines = part.splitlines()
            title = lines[0].strip()
            id_match = _ID_COMMENT.match(lines[1].strip()) if len(lines) > 1 else None
            if not id_match:
                raise ValueError(f"{path.name}: section {title!r} lacks an id comment")
            section_id = id_match.group(1)
            chunks.append(
                FaqChunk(
                    id=section_id,
                    language=language,
                    title=title,
                    text="\n".join(lines[2:]).strip(),
                    source=f"{path.name}#{section_id}",
                )
            )
    return chunks
