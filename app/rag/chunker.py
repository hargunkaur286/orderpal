"""Splits markdown documents into retrieval-sized chunks.

Strategy: structure-aware. Policy docs are written as one topic per `##` section, so each section
is a natural chunk. Splitting there keeps a rule and its exceptions together, which a fixed
"every 500 characters" split would cut in half.

Every chunk is prefixed with "Doc title > Section heading". A section like "Time limits" means
nothing on its own; "Refund Policy > Time limits" tells both the embedding model and the LLM
what the chunk is about.
"""
import re
from dataclasses import dataclass

MAX_CHARS = 1200       # roughly 300 tokens; bigger sections get split by paragraph
OVERLAP_PARAS = 1      # paragraphs repeated between consecutive pieces of a long section


@dataclass
class Chunk:
    index: int
    content: str


def _split_long(paragraphs: list[str]) -> list[list[str]]:
    """Packs paragraphs into groups under MAX_CHARS, repeating the last paragraph(s) of one
    group at the start of the next (overlap), so a sentence that depends on the previous
    paragraph still has its context."""
    groups, current = [], []
    for para in paragraphs:
        if current and sum(len(p) for p in current) + len(para) > MAX_CHARS:
            groups.append(current)
            current = current[-OVERLAP_PARAS:] if OVERLAP_PARAS else []
        current.append(para)
    if current:
        groups.append(current)
    return groups


def chunk_markdown(text: str) -> list[Chunk]:
    title = text.splitlines()[0].lstrip("# ").strip()
    # Split right before every "## " heading. Part 0 is the intro under the "# " title.
    parts = re.split(r"(?m)^(?=## )", text)
    chunks: list[Chunk] = []
    for part in parts[1:]:                         # skip the intro: here it's only a disclaimer
        heading, _, body = part.partition("\n")
        heading = heading.lstrip("# ").strip()
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        for group in _split_long(paragraphs):
            content = f"{title} > {heading}\n\n" + "\n\n".join(group)
            chunks.append(Chunk(index=len(chunks), content=content))
    return chunks
