import html
import logging
import re
import time
from typing import Dict, List, Tuple

import requests

from config import Config
from providers.base_provider import BaseProvider, SearchResult
from services.matcher import extract_features

logger = logging.getLogger(__name__)


class NaverProvider(BaseProvider):
    """
    네이버 쇼핑 provider.

    운영 안정성 기능:
    - 요청 간 지연
    - 429 지수 백오프 재시도
    - 동일 query in-memory 캐시
    """

    name = "naver"
    api_url = "https://openapi.naver.com/v1/search/shop.json"

    def __init__(self, config: Config):
        self.config = config
        self.last_error_message = ""
        self.last_error_type = ""
        self.last_raw_count = 0
        self.last_pages_called = 0

        # 실행 중 캐시 (동일 query 재호출 방지)
        self._query_cache: Dict[str, Dict] = {}

        # 실행 통계
        self.api_call_count = 0
        self.rate_limit_count = 0
        self.retry_count = 0
        self.api_raw_zero_count = 0

    def search(self, query: str, max_seconds: float | None = None) -> List[SearchResult]:
        self.last_error_message = ""
        self.last_error_type = ""
        self.last_raw_count = 0
        self.last_pages_called = 0
        if self.config.USE_MOCK:
            return self._search_mock(query)
        return self._search_real(query, max_seconds=max_seconds)

    def _build_query_candidates(self, original_query: str) -> List[str]:
        """
        검색 후보를 아래 순서로 만듭니다.
        1) 원본
        2) 브랜드 + 원본
        3) 핵심 토큰
        4) 브랜드 + 핵심 토큰
        5) 핵심 토큰 + 수량
        6) 브랜드 + 핵심 토큰 + 수량
        """
        features = extract_features(original_query)
        base_query = original_query.strip()
        core_query = " ".join(features.core_tokens).strip() or base_query

        qty_tokens = []
        qty_tokens.extend([f"{x}인" for x in sorted(features.person_counts)])
        qty_tokens.extend([f"{x}p" for x in sorted(features.piece_counts)])
        qty_part = " ".join(qty_tokens).strip()
        core_with_qty = f"{core_query} {qty_part}".strip() if qty_part else core_query

        brand_prefixes = getattr(self.config, "SEARCH_BRAND_PREFIXES", []) or []

        # safe_fast에서는 후보 수를 최소화해서 "실행 완료 보장" 우선
        if self.config.SEARCH_SPEED_MODE == "safe_fast":
            first_brand = brand_prefixes[0] if brand_prefixes else ""
            candidates: List[str] = [
                base_query,  # 원본
                f"{first_brand} {base_query}".strip() if first_brand else "",  # 브랜드 + 원본
                core_query,  # 핵심 토큰
                f"{first_brand} {core_query}".strip() if first_brand else "",  # 브랜드 + 핵심 토큰
                core_with_qty,  # 핵심 토큰 + 수량
                f"{first_brand} {core_with_qty}".strip() if first_brand else "",  # 브랜드 + 핵심 토큰 + 수량
            ]
        else:
            candidates = [
                base_query,
                *[f"{brand} {base_query}".strip() for brand in brand_prefixes],
                core_query,
                *[f"{brand} {core_query}".strip() for brand in brand_prefixes],
                core_with_qty,
                *[f"{brand} {core_with_qty}".strip() for brand in brand_prefixes],
            ]

        # 순서 유지 + 중복 제거
        dedup = []
        seen = set()
        for q in candidates:
            if q and q not in seen:
                dedup.append(q)
                seen.add(q)

        max_candidates = max(getattr(self.config, "NAVER_MAX_QUERY_CANDIDATES", 3), 1)
        limited = dedup[:max_candidates]
        logger.info("[NAVER] query 후보 순서(상한 적용)=%s", limited)
        return limited

    def _call_api_with_retry(
        self,
        query: str,
        start: int,
        headers: Dict[str, str],
        deadline: float | None = None,
    ) -> Tuple[Dict, str]:
        """429 대응: 지연 + 지수 백오프 재시도."""
        cache_key = f"{query}::start={start}"
        if cache_key in self._query_cache:
            logger.info("[NAVER] cache hit query=%s start=%s", query, start)
            return self._query_cache[cache_key], "CACHE"

        last_error = ""
        for attempt in range(1, self.config.NAVER_MAX_RETRIES + 1):
            if deadline is not None and time.perf_counter() >= deadline:
                self.last_error_type = "PRODUCT_TIMEOUT"
                self.last_error_message = "검색 시간 초과"
                return {"total": 0, "items": []}, "TIMEOUT"

            # 요청 간 기본 지연
            time.sleep(self.config.NAVER_REQUEST_DELAY_MS / 1000.0)

            params = {
                "query": query,
                "display": min(max(self.config.NAVER_DISPLAY_COUNT, 1), 100),
                "sort": "sim",
                "start": start,
            }

            self.api_call_count += 1
            logger.info("[NAVER] API 호출 시작 여부=True / attempt=%s / query=%s", attempt, query)
            try:
                response = requests.get(
                    self.api_url,
                    headers=headers,
                    params=params,
                    timeout=self.config.REQUEST_TIMEOUT,
                )
                logger.info("[NAVER] 응답 status code=%s", response.status_code)

                # 429는 별도 처리
                if response.status_code == 429:
                    self.rate_limit_count += 1
                    self.retry_count += 1
                    wait_seconds = self.config.NAVER_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning("[NAVER] 429 발생 -> backoff %.1fs", wait_seconds)
                    if attempt >= self.config.NAVER_MAX_RETRIES:
                        self.last_error_type = "API_RATE_LIMIT"
                        self.last_error_message = "API 429 / 호출 제한"
                        return {"total": 0, "items": []}, "RATE_LIMIT"
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                payload = response.json()
                self._query_cache[cache_key] = payload
                return payload, "OK"

            except requests.RequestException as e:
                last_error = str(e)
                logger.error("[NAVER] 에러 메시지=%s", last_error)
                if attempt >= self.config.NAVER_MAX_RETRIES:
                    self.last_error_type = "API_ERROR"
                    self.last_error_message = f"네이버 API 호출 실패: {last_error}"
                    return {"total": 0, "items": []}, "ERROR"
                self.retry_count += 1
                wait_seconds = self.config.NAVER_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                time.sleep(wait_seconds)

        self.last_error_type = "API_ERROR"
        self.last_error_message = f"네이버 API 호출 실패: {last_error}"
        return {"total": 0, "items": []}, "ERROR"

    def _search_real(self, query: str, max_seconds: float | None = None) -> List[SearchResult]:
        """
        [진짜 네이버 API 호출 부분]
        - 서버 환경변수(NAVER_CLIENT_ID/SECRET)만 사용
        """
        has_client_id = bool(self.config.NAVER_CLIENT_ID)
        has_client_secret = bool(self.config.NAVER_CLIENT_SECRET)

        logger.info("[NAVER] USE_MOCK=%s", self.config.USE_MOCK)
        logger.info("[NAVER] NAVER_CLIENT_ID 존재 여부=%s", has_client_id)

        if not has_client_id or not has_client_secret:
            self.last_error_type = "API_KEY_MISSING"
            self.last_error_message = "네이버 API 키가 없어 REAL 검색을 할 수 없습니다"
            logger.error("[NAVER] %s", self.last_error_message)
            return []

        headers = {
            "X-Naver-Client-Id": self.config.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": self.config.NAVER_CLIENT_SECRET,
        }
        deadline = time.perf_counter() + max_seconds if max_seconds else None

        query_candidates = self._build_query_candidates(query)
        raw_items = []
        self.last_pages_called = 0
        should_stop_search = False

        for idx, q in enumerate(query_candidates, start=1):
            if deadline is not None and time.perf_counter() >= deadline:
                self.last_error_type = "PRODUCT_TIMEOUT"
                self.last_error_message = "검색 시간 초과"
                logger.warning("[NAVER] 제품 제한시간 초과 / query=%s", query)
                break
            logger.info("[NAVER] query 후보 시도 %s/%s: %s", idx, len(query_candidates), q)
            for page in range(1, max(self.config.NAVER_MAX_PAGES, 1) + 1):
                if deadline is not None and time.perf_counter() >= deadline:
                    self.last_error_type = "PRODUCT_TIMEOUT"
                    self.last_error_message = "검색 시간 초과"
                    should_stop_search = True
                    logger.warning("[NAVER] 페이지 탐색 중 제품 제한시간 초과 / query=%s", query)
                    break
                start = 1 + (page - 1) * self.config.NAVER_DISPLAY_COUNT
                payload, call_status = self._call_api_with_retry(q, start, headers, deadline=deadline)
                self.last_pages_called += 1

                total = payload.get("total", 0)
                items = payload.get("items", [])

                logger.info("[NAVER] 검색 query=%s / page=%s / start=%s", q, page, start)
                logger.info("[NAVER] 응답 total=%s", total)
                logger.info("[NAVER] 응답 items 개수=%s", len(items))

                for sample_idx, item in enumerate(items[:3], start=1):
                    logger.info(
                        "[NAVER] sample[%s] title=%s | mallName=%s | lprice=%s | link=%s",
                        sample_idx,
                        item.get("title", ""),
                        item.get("mallName", ""),
                        item.get("lprice", ""),
                        item.get("link", ""),
                    )

                if call_status == "RATE_LIMIT":
                    break
                if call_status == "TIMEOUT":
                    should_stop_search = True
                    break
                if call_status == "ERROR":
                    should_stop_search = True
                    logger.warning("[NAVER] API ERROR 재발 방지: 남은 query/page 탐색 중단 / query=%s", query)
                    break

                raw_items.extend(items)

                # 기본은 첫 페이지만, 충분한 후보가 없을 때만 다음 페이지
                if page == 1 and len(items) >= 20:
                    # recall 우선: safe_fast에서도 최소 query 구간에서는 2페이지를 실제로 확인
                    min_queries_to_try = max(getattr(self.config, "NAVER_MIN_QUERIES_TO_TRY", 1), 1)
                    keep_page2 = self.config.SEARCH_SPEED_MODE == "safe_fast" and idx <= min(len(query_candidates), min_queries_to_try)
                    if not keep_page2:
                        logger.info("[NAVER] 첫 페이지 후보 충분 -> 다음 페이지 생략")
                        break
                if len(items) == 0:
                    break

            if getattr(self, "last_error_type", "") == "API_RATE_LIMIT":
                break
            if should_stop_search:
                break

            if raw_items:
                # recall 우선: safe_fast에서도 최소 query 횟수까지는 추가 시도
                min_queries_to_try = max(getattr(self.config, "NAVER_MIN_QUERIES_TO_TRY", 1), 1)
                if self.config.SEARCH_SPEED_MODE == "safe_fast" and idx < min(len(query_candidates), min_queries_to_try):
                    logger.info(
                        "[NAVER] safe_fast recall 보강: raw_items 존재하지만 추가 query 시도 계속 (%s/%s)",
                        idx,
                        min(len(query_candidates), min_queries_to_try),
                    )
                    continue

                logger.info("[NAVER] 결과가 나온 query=%s", q)
                break

        dedup = {}
        for item in raw_items:
            key = item.get("link") or item.get("title") or str(id(item))
            dedup[key] = item
        items = list(dedup.values())
        self.last_raw_count = len(items)

        if self.last_raw_count == 0 and not self.last_error_type:
            self.api_raw_zero_count += 1
            self.last_error_type = "API_RAW_ZERO"
            logger.warning("[NAVER] API_RAW_ZERO: query=%s", query)

        results: List[SearchResult] = []
        for item in items:
            title_raw = item.get("title", "")
            title = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()

            try:
                price = int(item.get("lprice", 0))
            except (TypeError, ValueError):
                price = None

            mall_name = item.get("mallName") or "쇼핑몰 정보 없음"
            link = item.get("link") or ""

            results.append(
                SearchResult(
                    title=title,
                    price=price,
                    shipping_fee=None,
                    mall_name=mall_name,
                    link=link,
                )
            )
        return results

    def _search_mock(self, query: str) -> List[SearchResult]:
        return [
            SearchResult(
                title=f"{query} 13P 홈세트",
                price=39900,
                shipping_fee=3000,
                mall_name="네이버몰A(예시)",
                link="https://example.com/naver/a",
            ),
            SearchResult(
                title=f"{query} 13p 할인 특가",
                price=34900,
                shipping_fee=None,
                mall_name="네이버몰B(예시)",
                link="https://example.com/naver/b",
            ),
            SearchResult(
                title=f"{query} 4인 20P 세트",
                price=29900,
                shipping_fee=0,
                mall_name="네이버몰C(예시)",
                link="https://example.com/naver/c",
            ),
        ]
