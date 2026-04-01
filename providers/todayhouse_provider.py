from typing import List

from config import Config
from providers.base_provider import BaseProvider, SearchResult


class TodayHouseProvider(BaseProvider):
    """오늘의집 provider placeholder."""

    name = "todayhouse"

    def __init__(self, config: Config):
        self.config = config

    def search(self, query: str, max_seconds: float | None = None) -> List[SearchResult]:
        _ = max_seconds
        if self.config.USE_MOCK:
            return self._search_mock(query)
        return self._search_real(query)

    def _search_real(self, query: str) -> List[SearchResult]:
        _ = query
        return []

    def _search_mock(self, query: str) -> List[SearchResult]:
        return [
            SearchResult(
                title=f"{query} 2인 13P 오늘의집 에디션",
                price=32900,
                shipping_fee=0,
                mall_name="오늘의집(예시)",
                link="https://example.com/todayhouse/a",
            ),
            SearchResult(
                title=f"{query} 2인 21P 오늘의집 프리미엄",
                price=45900,
                shipping_fee=2500,
                mall_name="오늘의집(예시)",
                link="https://example.com/todayhouse/b",
            ),
        ]
