"""Web search service using DuckDuckGo."""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Web search result."""
    title: str
    url: str
    snippet: str


class WebSearchService:
    """Web search using DuckDuckGo (no API key required)."""

    def __init__(self):
        self._ddg = None

    def _get_ddg(self):
        """Lazy load DuckDuckGo search."""
        if self._ddg is None:
            try:
                from duckduckgo_search import DDGS
                self._ddg = DDGS()
            except ImportError:
                logger.warning("duckduckgo-search not installed")
                return None
        return self._ddg

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Search the web for a query.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of search results
        """
        ddg = self._get_ddg()
        if not ddg:
            return []

        try:
            results = []
            # DuckDuckGo search is synchronous, run in executor
            import asyncio
            loop = asyncio.get_event_loop()

            def do_search():
                return list(ddg.text(query, max_results=max_results))

            raw_results = await loop.run_in_executor(None, do_search)

            for r in raw_results:
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", r.get("link", "")),
                    snippet=r.get("body", r.get("snippet", "")),
                ))

            return results

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def format_results_for_context(self, results: List[SearchResult]) -> str:
        """Format search results for LLM context."""
        if not results:
            return "No search results found."

        lines = ["Web search results:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   {r.snippet}")
            lines.append(f"   Source: {r.url}\n")

        return "\n".join(lines)

    def format_results_for_user(self, results: List[SearchResult]) -> str:
        """Format search results for user display."""
        if not results:
            return "No results found."

        lines = ["🔍 **Search Results:**\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. [{r.title}]({r.url})")
            lines.append(f"   {r.snippet[:150]}...\n" if len(r.snippet) > 150 else f"   {r.snippet}\n")

        return "\n".join(lines)

