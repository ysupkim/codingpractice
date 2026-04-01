import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from providers.base_provider import SearchResult
from services.excel_reader import BaseProduct
from services.matcher import ALLOWED_ITEM_PAIR, extract_features, evaluate_match

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
    evaluated_candidate_count: int = 0
    fallback_used: bool = False
    reranked_top_titles: List[str] = field(default_factory=list)


def _add_reason(info: ComparisonDebugInfo, reason: str):
    info.reasons[reason] = info.reasons.get(reason, 0) + 1


def compare_product_with_results(
    base: BaseProduct,
    search_results: List[SearchResult],
    max_evaluation_candidates: int | None = None,
) -> Tuple[List[ComparisonResult], ComparisonDebugInfo]:
    compared: List[ComparisonResult] = []
    debug = ComparisonDebugInfo(raw_count=len(search_results))

    FULL_EVALUATION_THRESHOLD = 50
    base_features = extract_features(base.name)
    evaluated_links = set()

    def _relevance(item: SearchResult, idx: int) -> float:
        cand = extract_features(item.title)
        score = 0.0

        if cand.hard_negative_tokens:
            score -= 5.0

        if base_features.design_candidate_tokens and cand.design_candidate_tokens:
            if base_features.design_candidate_tokens & cand.design_candidate_tokens:
                score += 3.0

        if base_features.item_type_tokens and cand.item_type_tokens:
            if base_features.item_type_tokens & cand.item_type_tokens:
                score += 2.5
            else:
                for b in base_features.item_type_tokens:
                    for c in cand.item_type_tokens:
                        if (b, c) in ALLOWED_ITEM_PAIR:
                            score += 2.0
                            break

        if base_features.piece_counts and cand.piece_counts and (base_features.piece_counts & cand.piece_counts):
            score += 2.0
        if base_features.person_counts and cand.person_counts and (base_features.person_counts & cand.person_counts):
            score += 1.5
        if base_features.shape_tokens and cand.shape_tokens and (base_features.shape_tokens & cand.shape_tokens):
            score += 1.0

        # tie-break: 원래 순서 가중치(앞쪽 소폭 우선)
        score += max(0.0, 0.001 * (1000 - idx))
        return score

    ranked_candidates = search_results
    if len(search_results) > FULL_EVALUATION_THRESHOLD:
        ranked = [(item, _relevance(item, idx), idx) for idx, item in enumerate(search_results)]
        ranked.sort(key=lambda x: x[1], reverse=True)
        ranked_candidates = [x[0] for x in ranked]
        debug.reranked_top_titles = [x[0].title for x in ranked[:5]]

    def _evaluate(items: List[SearchResult], mark_fallback: bool = False):
        if mark_fallback:
            debug.fallback_used = True
        for item in items:
            dedup_key = item.link or item.title
            if dedup_key and dedup_key in evaluated_links:
                continue
            if dedup_key:
                evaluated_links.add(dedup_key)
            debug.evaluated_candidate_count += 1
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
    # 못잡음 최소화를 위해 평가량을 넓게 가져감
    if len(ranked_candidates) <= FULL_EVALUATION_THRESHOLD:
        _evaluate(ranked_candidates)
    else:
        base_limit = max_evaluation_candidates or len(ranked_candidates)
        primary_limit = min(len(ranked_candidates), max(base_limit * 3, 120))
        primary_candidates = ranked_candidates[:primary_limit]
        remaining_candidates = ranked_candidates[primary_limit:]
        _evaluate(primary_candidates)
        if not compared and remaining_candidates:
            _add_reason(debug, f"후보 fallback 재평가 {len(remaining_candidates)}건")
            _evaluate(remaining_candidates, mark_fallback=True)

    debug.passed_count = len(compared)
    if debug.dropped_count == 0 and debug.raw_count > 0:
        _add_reason(debug, "탈락 없음")
    elif debug.raw_count == 0:
        _add_reason(debug, "API raw 0건")

    return compared, debug
