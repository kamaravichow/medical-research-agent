"""Citation formatting: Vancouver/AMA-style text, RIS and BibTeX exports."""

from __future__ import annotations

import re

from .models import Article


def _authors_short(authors: list[str], max_authors: int = 6) -> str:
    if not authors:
        return ""
    if len(authors) > max_authors:
        return ", ".join(authors[:3]) + ", et al"
    return ", ".join(authors)


def vancouver(article: Article) -> str:
    parts = []
    authors = _authors_short(article.authors)
    if authors:
        parts.append(f"{authors}.")
    parts.append(f"{article.title.rstrip('.')}.")
    if article.journal:
        parts.append(f"{article.journal}.")
    if article.year:
        parts.append(f"{article.year}.")
    if article.doi:
        parts.append(f"doi:{article.doi}.")
    if article.pmid:
        parts.append(f"PMID: {article.pmid}.")
    if article.is_preprint:
        parts.append("[Preprint - not peer reviewed]")
    return " ".join(parts)


def ris(articles: list[Article]) -> str:
    lines: list[str] = []
    for a in articles:
        lines.append("TY  - " + ("UNPB" if a.is_preprint else "JOUR"))
        lines.append(f"TI  - {a.title}")
        lines += [f"AU  - {au}" for au in a.authors]
        if a.journal:
            lines.append(f"JO  - {a.journal}")
        if a.year:
            lines.append(f"PY  - {a.year}")
        if a.doi:
            lines.append(f"DO  - {a.doi}")
        if a.pmid:
            lines.append(f"AN  - PMID:{a.pmid}")
        if a.url:
            lines.append(f"UR  - {a.url}")
        if a.abstract:
            lines.append(f"AB  - {a.abstract}")
        lines += [f"KW  - {k}" for k in a.mesh_terms[:10]]
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


def _bibkey(a: Article) -> str:
    first = re.sub(r"[^A-Za-z]", "", (a.authors[0].split()[0] if a.authors else "anon"))
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", a.title)), "paper")
    return f"{first.lower()}{a.year or ''}{word.lower()}"


def bibtex(articles: list[Article]) -> str:
    entries = []
    for a in articles:
        fields = {
            "title": "{" + a.title.replace("{", "").replace("}", "") + "}",
            "author": " and ".join(a.authors) or None,
            "journal": a.journal,
            "year": str(a.year) if a.year else None,
            "doi": a.doi,
            "pmid": a.pmid,
            "url": a.url,
            "note": "Preprint" if a.is_preprint else None,
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        entries.append(f"@{'unpublished' if a.is_preprint else 'article'}{{{_bibkey(a)},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"
