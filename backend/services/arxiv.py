"""
arXiv preprint search.

We surface relevant grid-operations / energy / datacenter papers next to
report sections so the operator has a primary-source jumping-off point.
arXiv's public Atom API is free, key-less, and rate-limit-friendly when
hit at our scale (a handful of searches per pipeline run, cached for
24 hours per ``backend/utils/cache.py``).

This module deliberately stays small — three search builders, one XML
parser, and a module-level singleton client (``arxiv_client``). Callers
(pipeline agents + the ``/api/arxiv/search`` endpoint) only touch the
async ``search`` methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from xml.etree import ElementTree as ET

import httpx

from backend.config import settings
from backend.utils.cache import arxiv_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── XML namespaces used in arXiv Atom responses ───────────────────────── #

_ATOM_NS = "http://www.w3.org/2005/Atom"


def _tag(name: str) -> str:
    """Format an Atom-namespaced tag for ``Element.find()`` / ``findall()``."""
    return f"{{{_ATOM_NS}}}{name}"


# ── Result shape ──────────────────────────────────────────────────────── #


@dataclass(frozen=True)
class _PaperFields:
    """The subset of arXiv entry fields we surface to the frontend.

    Kept as a private dataclass so the field set is documented in one
    place; the public API still returns plain dicts (callers serialise
    them straight into the report blob, so dataclasses would just add a
    ``.dict()`` step at every call site).
    """

    arxiv_id: str
    title: str
    authors: list[str]
    summary: str
    published: str
    url: str
    categories: list[str]

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors[:5],
            "summary": self.summary[:600],
            "published": self.published,
            "url": self.url,
            "categories": self.categories,
        }


# ── XML parsing helpers ───────────────────────────────────────────────── #


def _first_text(parent: ET.Element, tag: str) -> str:
    """Return the text of ``parent``'s first child matching ``tag``, or
    an empty string. Whitespace is left untouched — callers normalise."""
    child = parent.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text


def _collapse_whitespace(s: str) -> str:
    """Replace any run of whitespace (incl. newlines) with a single space.
    arXiv summaries / titles are pretty-printed and would otherwise show
    as multi-line blocks in the report."""
    return " ".join(s.split())


def _extract_arxiv_id(entry: ET.Element) -> str:
    raw = _first_text(entry, _tag("id"))
    return raw.replace("http://arxiv.org/abs/", "").strip()


def _extract_authors(entry: ET.Element) -> list[str]:
    return [
        _first_text(author, _tag("name"))
        for author in entry.findall(_tag("author"))
    ]


def _extract_html_url(entry: ET.Element, arxiv_id: str) -> str:
    for link in entry.findall(_tag("link")):
        if link.get("type") == "text/html":
            return link.get("href", "")
    return f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""


def _extract_categories(entry: ET.Element) -> list[str]:
    return [c.get("term", "") for c in entry.findall(_tag("category"))]


def _parse_entry(entry: ET.Element) -> _PaperFields | None:
    """Convert one ``<entry>`` element into a ``_PaperFields``. Returns
    ``None`` when the entry has no title — arXiv occasionally returns
    placeholder rows for in-progress submissions."""
    title = _collapse_whitespace(_first_text(entry, _tag("title")))
    if not title:
        return None
    arxiv_id = _extract_arxiv_id(entry)
    return _PaperFields(
        arxiv_id=arxiv_id,
        title=title,
        authors=_extract_authors(entry),
        summary=_collapse_whitespace(_first_text(entry, _tag("summary"))),
        published=_first_text(entry, _tag("published"))[:10],
        url=_extract_html_url(entry, arxiv_id),
        categories=_extract_categories(entry),
    )


def _parse_atom_feed(xml_text: str) -> list[dict]:
    """Top-level: parse an arXiv Atom feed string into a list of paper
    dicts. Returns ``[]`` on parse errors so a malformed upstream payload
    never crashes the pipeline."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("arXiv XML parse error: %s", exc)
        return []

    papers: list[dict] = []
    for entry in root.findall(_tag("entry")):
        parsed = _parse_entry(entry)
        if parsed is not None:
            papers.append(parsed.to_dict())
    return papers


# ── Query builders ────────────────────────────────────────────────────── #
#
# arXiv's search syntax is roughly Lucene-shaped: ``ti:`` searches the
# title, ``abs:`` searches the abstract, ``all:`` searches everything.
# Boolean operators are AND / OR (case-sensitive) with parentheses.


def _region_query(iso_code: str) -> str:
    return (
        f'ti:"{iso_code}" OR abs:"{iso_code}" '
        f'AND (ti:"datacenter" OR abs:"workload placement" OR abs:"siting" '
        f'OR abs:"locational marginal" OR abs:"transmission")'
    )


def _workload_query(workload_name: str) -> str:
    return (
        f'all:"{workload_name}" AND '
        f'(ti:"datacenter siting" OR ti:"workload placement" OR '
        f'ti:"carbon-aware" OR ti:"grid integration")'
    )


# ── Client ────────────────────────────────────────────────────────────── #


class ArXivClient:
    """Async wrapper around the arXiv public Atom API."""

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url or settings.arxiv_base_url
        self._timeout = timeout_seconds

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[dict]:
        """Run an arXiv query, cached for 24 hours per ``(query, max_results)``.

        Returns an empty list on any failure (timeouts, 5xx, parse
        errors) — callers should treat arXiv as best-effort context.
        """
        results_cap = max_results or settings.arxiv_max_results
        cache_key = f"search:{query}:{results_cap}"

        cached = await arxiv_cache.aget(cache_key)
        if cached is not None:
            return cached

        params = {
            "search_query": query,
            "start": 0,
            "max_results": results_cap,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.get(self._base_url, params=params)
                response.raise_for_status()
                papers = _parse_atom_feed(response.text)
        except Exception as exc:
            logger.warning("arXiv search failed for %r: %s", query, exc)
            return []

        await arxiv_cache.aset(cache_key, papers)
        return papers

    async def search_for_region(self, iso_code: str, workload_name: str) -> list[dict]:
        """Region-scoped query — used by region-insight builders."""
        return await self.search(_region_query(iso_code))

    async def search_for_workload(self, workload_name: str) -> list[dict]:
        """Workload-scoped query — used by plan synthesis to surface
        workload-class context (e.g. AI training, inference)."""
        return await self.search(_workload_query(workload_name))


# Module-level singleton — agents and the live router both import this
# directly. Cheap to instantiate, but the cache benefits compound when
# every caller shares the same instance.
arxiv_client = ArXivClient()


__all__: Iterable[str] = ("ArXivClient", "arxiv_client")
