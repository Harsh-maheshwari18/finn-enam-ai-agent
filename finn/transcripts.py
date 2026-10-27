"""Transcript text: extraction, normalisation for matching, speaker turns.

Artefacts observed in real NSE-filed PDFs (2026-10-27):
- ligatures: "reﬂects" (U+FB02) -> handled by NFKC
- broken "ff" glyph rendered as "Ư": "taper o Ư" = "taper off", "diƯicult" = "difficult" (TCS)
- digit zero rendered as letter "O" inside numbers: "2O7OO.O3" (HDFCBANK results PDF)
- hyphenation spacing: "medium - to long -term" (POLYCAB)
The original extracted text is always kept; normalisation is only used to *locate* a quote.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

SPEAKER = re.compile(r"(?m)^\s*([A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){0,3}|Moderator)\s*:\s")


def pdf_pages(path) -> list[str]:
    import pypdf
    reader = pypdf.PdfReader(str(path))
    out = []
    for p in reader.pages:
        try:
            out.append(p.extract_text() or "")
        except Exception:                      # a bad page must not sink the document
            out.append("")
    return out


def looks_scanned(pages: list[str], min_chars: int = 200) -> bool:
    """True if most pages carry no text layer (image-only PDF)."""
    if not pages:
        return True
    empty = sum(1 for p in pages if len(p.strip()) < min_chars)
    return empty / len(pages) > 0.5


def fix_numeric_o(s: str) -> str:
    """'2O7OO.O3' -> '20700.03'. Only touches O between/next to digits, so words are untouched."""
    def fix(m):
        tok = m.group()
        return tok.replace("O", "0") if any(c.isdigit() for c in tok) else tok
    return re.sub(r"\b[\dO][\dO,.]*\b", fix, s)


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s?Ư", "ff", s)          # "taper o Ư or" -> "taper off or"
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


@dataclass(frozen=True)
class Turn:
    speaker: str
    page: int          # 1-based page where the turn starts
    text: str


def speaker_turns(pages: list[str]) -> list[Turn]:
    """Split a transcript into speaker turns, carrying the current speaker across page breaks."""
    turns: list[Turn] = []
    current, buf, start_page = None, [], 1
    for pno, page in enumerate(pages, start=1):
        pos = 0
        for m in SPEAKER.finditer(page):
            buf.append(page[pos:m.start()])
            if current is not None:
                turns.append(Turn(current, start_page, "".join(buf).strip()))
            current, buf, start_page, pos = m.group(1), [], pno, m.end()
        buf.append(page[pos:])
    if current is not None:
        turns.append(Turn(current, start_page, "".join(buf).strip()))
    return turns


def management_names(pages: list[str]) -> set[str]:
    """Names listed under the 'MANAGEMENT:' header block on the first pages, if present."""
    head = " ".join(pages[:3])
    m = re.search(r"MANAGEMENT\s*:(.*?)(?:Moderator\s*:|MODERATOR|Page 2 of|\Z)", head, re.S)
    if not m:
        return set()
    names = re.findall(r"(?:MR\.|MS\.|MRS\.|DR\.)\s+([A-Z][A-Z .'\-]+?)\s+[–-]", m.group(1))
    return {n.strip().title() for n in names}


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    page: Optional[int]
    method: Optional[str]      # "exact" | "normalised"


def locate_quote(quote: str, pages: list[str], hint_page: Optional[int] = None) -> QuoteCheck:
    """A quote is accepted only if it occurs in the source text: verbatim, or after the reversible
    normalisation above. No fuzzy similarity: a paraphrase must fail."""
    if not quote or len(quote.strip()) < 15:
        return QuoteCheck(False, None, None)
    order = list(range(1, len(pages) + 1))
    if hint_page and 1 <= hint_page <= len(pages):
        order.remove(hint_page)
        order.insert(0, hint_page)
    nq = normalise(quote)
    for p in order:
        if quote in pages[p - 1]:
            return QuoteCheck(True, p, "exact")
    for p in order:
        if nq in normalise(pages[p - 1]):
            return QuoteCheck(True, p, "normalised")
    # quotes may straddle a page break
    for p in range(1, len(pages)):
        if nq in normalise(pages[p - 1] + " " + pages[p]):
            return QuoteCheck(True, p, "normalised")
    return QuoteCheck(False, None, None)
