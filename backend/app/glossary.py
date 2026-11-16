"""Glossary matching: which required terms apply to an English line.

Matching is case-insensitive on whole words and accepts simple English plurals
(elephant matches "elephants"; multi-word terms match too, e.g. "ice cream").
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    source: str
    target: str


def _pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.strip().split()]
    words[-1] += r"(?:s|es)?"           # elephant(s), box(es)
    return re.compile(r"(?<![\w'])" + r"\s+".join(words) + r"(?![\w'])", re.IGNORECASE)


def terms_for(text: str, terms: list[Term]) -> list[Term]:
    """Terms whose English side appears in text (longest first, so 'ice cream' beats 'ice')."""
    found, taken = [], []
    for t in sorted(terms, key=lambda t: -len(t.source)):
        for m in _pattern(t.source).finditer(text):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                taken.append((m.start(), m.end())); found.append(t); break
    return found


def missing_terms(output: str, required: list[Term]) -> list[Term]:
    return [t for t in required if t.target not in output]


def load_terms(source_lang: str, target_lang: str) -> list[Term]:
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import GlossaryTerm
    with SessionLocal() as db:
        return [Term(g.source_term, g.target_term) for g in db.scalars(select(GlossaryTerm).where(
            GlossaryTerm.source_lang == source_lang, GlossaryTerm.target_lang == target_lang))]
