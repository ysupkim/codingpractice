from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchResult:
    """검색 결과 1건을 표준 형태로 관리합니다."""

    title: str
    price: Optional[int]
    shipping_fee: Optional[int]
    mall_name: str
    link: str


class BaseProvider(ABC):
    """검색 플랫폼 공통 인터페이스입니다."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str) -> List[SearchResult]:
        raise NotImplementedError
