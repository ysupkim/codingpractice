import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from providers.base_provider import SearchResult
from services.excel_reader import BaseProduct
from services.matcher import evaluate_match

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    base_product_name: str
    base_online_discount_price: int
    found_product_name: str
    sale_price: int | None
    mall_name: str
    product_link: str
    is_below_base: bool
    shipping_fee_known: bool
    status: str
    is_problem: bool


@dataclass
class ComparisonDebugInfo:
    raw_count: int = 0
    passed_count: int = 0
    dropped_count: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)


def _add_reason(info: ComparisonDebugInfo, reason: str):
    info.reasons[reason] = info.reasons.get(reason, 0) + 1


def compare_product_with_results(
    base: BaseProduct,
    search_results: List[SearchResult],
    max_evaluation_candidates: int | None = None,
) -> Tuple[List[ComparisonResult], ComparisonDebugInfo]:
    compared: List[ComparisonResult] = []
    debug = ComparisonDebugInfo(raw_count=len(search_results))
    candidates = search_results
    fallback_candidates: List[SearchResult] = []
    # 실행 완료 보장을 위해 평가 대상 상한 적용 (정확도보다 속도 우선)
    if max_evaluation_candidates is not None and max_evaluation_candidates > 0:
        candidates = search_results[:max_evaluation_candidates]
        skipped = len(search_results) - len(candidates)
        if skipped > 0:
            _add_reason(debug, f"후보 상한으로 {skipped}건 생략")
            # 앞쪽 후보에서 모두 탈락하면 뒤쪽 후보를 추가로 보는 fallback (미탐 완화)
            fallback_limit = max(max_evaluation_candidates, 10)
            fallback_candidates = search_results[max_evaluation_candidates : max_evaluation_candidates + fallback_limit]

    def _evaluate(items: List[SearchResult]):
        for item in items:
            matched, reason, similarity = evaluate_match(base.name, item.title)
            if not matched:
                debug.dropped_count += 1
                _add_reason(debug, reason)
                continue

            if item.price is None or not item.link:
                logger.info("[COMPARE] 링크/가격 누락: title=%s", item.title)
                debug.dropped_count += 1
                _add_reason(debug, "링크/가격 누락")
                continue

            shipping_fee_known = item.shipping_fee is not None
            shipping_fee = item.shipping_fee or 0
            total_price = item.price + shipping_fee

            is_below = total_price < base.online_discount_price
            status = "가격 문제 있음" if is_below else "가격 문제 없음"
            if not is_below:
                logger.info(
                    "[COMPARE] 가격 비교 조건 미충족: total=%s base=%s / title=%s / sim=%.3f",
                    total_price,
                    base.online_discount_price,
                    item.title,
                    similarity,
                )

            compared.append(
                ComparisonResult(
                    base_product_name=base.name,
                    base_online_discount_price=base.online_discount_price,
                    found_product_name=item.title,
                    sale_price=total_price,
                    mall_name=item.mall_name or "쇼핑몰 정보 없음",
                    product_link=item.link,
                    is_below_base=is_below,
                    shipping_fee_known=shipping_fee_known,
                    status=status,
                    is_problem=is_below,
                )
            )

    _evaluate(candidates)
    if not compared and fallback_candidates:
        _add_reason(debug, f"후보 fallback 재평가 {len(fallback_candidates)}건")
        _evaluate(fallback_candidates)

    debug.passed_count = len(compared)
    if debug.dropped_count == 0 and debug.raw_count > 0:
        _add_reason(debug, "탈락 없음")
    elif debug.raw_count == 0:
        _add_reason(debug, "API raw 0건")

    return compared, debug
