import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Set, Tuple

logger = logging.getLogger(__name__)

# evaluate_match 호출 횟수 (성능 측정용)
EVALUATE_MATCH_CALL_COUNT = 0

# -----------------------------
# 사전 기반 토큰
# -----------------------------
SHAPE_TOKENS = {
    "챠토우",
    "디멘션",
    "세느",
    "원형",
    "사각",
}

NOISE_TOKENS = {
    "한국도자기",
    "본차이나",
    "탑탑리빙",
    "노원",
    "중랑점",
    "프리미엄",
    "무료배송",
    "특가",
    "정품",
    "공식",
    "예쁜커피잔",
    "행사",
    "티맛세트",
    "티망포함",
    "티망",
    "japan",
    "신혼",
    "color",
    "세트상품",
    "사은품",
    "할인",
    "양귀비",
    "도안",
    "아트",
    "그림",
    "노프레임",
    "중형노프레임",
}

ONE_CHAR_DESIGN_TOKENS = {"연"}

NOISE_PATTERNS = [
    r"\b\d+\s*color\b",
    r"\[한국도자기\]",
    r"\[예단포장\]",
]

PIECE_UNIT_PATTERN = r"(?:pieces|piece|pcs|pc|p)"

# 세부 품목 타입
ITEM_TYPE_GROUPS = {
    "coffee_set": ["커피세트", "커피셋"],
    "coffee_cup_set": ["커피잔세트", "커피컵세트"],
    "coffee_cup_single": ["커피잔", "커피컵"],
    "mug_set": ["머그세트", "머그셋"],
    "mug_single": ["머그", "머그컵"],
    "lid_mug_set": ["뚜껑머그세트", "뚜껑머그셋"],
    "lid_mug_single": ["뚜껑머그"],
    "bansang": ["반상기"],
    "single_bansang": ["단반상기"],
    "tea_set": ["티세트", "티셋", "다기세트", "다기"],
    "tea_cup_set": ["티잔세트"],
    "tea_cup_single": ["티잔"],
    "calendar_dish": ["달력접시"],
    "dish_set": ["접시세트", "접시셋", "접시"],
    "home_set": ["홈세트", "홈세트", "홈 세트"],
    "art_or_frame": ["노프레임", "액자", "그림", "아트", "도안"],
    "vase": ["화병"],
    "utensil_holder": ["수저통"],
    "plating": ["플레이팅", "조개", "마블"],
}

# 보수적 허용 매트릭스
ALLOWED_ITEM_PAIR = {
    ("coffee_set", "coffee_set"),
    ("coffee_set", "coffee_cup_set"),
    ("coffee_set", "coffee_cup_single"),
    ("coffee_cup_set", "coffee_set"),
    ("coffee_cup_set", "coffee_cup_set"),
    ("coffee_cup_set", "coffee_cup_single"),
    ("coffee_cup_single", "coffee_set"),
    ("coffee_cup_single", "coffee_cup_set"),
    ("coffee_cup_single", "coffee_cup_single"),
    ("mug_set", "mug_set"),
    ("mug_set", "mug_single"),
    ("mug_single", "mug_set"),
    ("mug_single", "mug_single"),
    ("lid_mug_set", "lid_mug_set"),
    ("lid_mug_set", "lid_mug_single"),
    ("lid_mug_single", "lid_mug_set"),
    ("lid_mug_single", "lid_mug_single"),
    ("tea_set", "tea_set"),
    ("tea_set", "tea_cup_set"),
    ("tea_set", "tea_cup_single"),
    ("tea_cup_set", "tea_set"),
    ("tea_cup_set", "tea_cup_set"),
    ("tea_cup_set", "tea_cup_single"),
    ("tea_cup_single", "tea_set"),
    ("tea_cup_single", "tea_cup_set"),
    ("tea_cup_single", "tea_cup_single"),
    ("home_set", "home_set"),
    ("dish_set", "dish_set"),
    ("calendar_dish", "calendar_dish"),
    ("bansang", "bansang"),
    ("bansang", "single_bansang"),
    ("single_bansang", "bansang"),
    ("single_bansang", "single_bansang"),
}

STRICT_ITEM_REQUIRED = {
    "dish_set",
    "calendar_dish",
    "bansang",
    "single_bansang",
    "tea_set",
    "mug_set",
    "coffee_set",
}

HIGH_VOLUME_PIECE_THRESHOLD = 30


@dataclass
class NameFeatures:
    normalized: str
    clean_text: str
    core_tokens: List[str]
    design_candidate_tokens: Set[str]
    shape_tokens: Set[str]
    item_type_tokens: Set[str]
    noise_tokens: Set[str]
    piece_counts: Set[int]
    person_counts: Set[int]
    outer_set_counts: Set[int]
    has_bracket_piece_notation: bool
    bracket_parse_failed: bool
    years: Set[int]
    design_number_tokens: Set[str]


def _normalize_piece_units(text: str) -> str:
    return re.sub(PIECE_UNIT_PATTERN, "p", text, flags=re.IGNORECASE)


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = _normalize_piece_units(text)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^0-9a-zA-Z가-힣()\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_piece_info(norm: str) -> Tuple[Set[int], Set[int], bool, bool]:
    piece_counts: Set[int] = set()
    outer_set_counts: Set[int] = set()

    has_bracket_piece_notation = bool(re.search(r"\d+\s*\(\s*\d+\s*\)\s*p", norm))

    bracket_matches = re.findall(r"(\d+)\s*\(\s*(\d+)\s*\)\s*p", norm)
    for outer, inner in bracket_matches:
        outer_set_counts.add(int(outer))
        piece_counts.add(int(inner))

    for value in re.findall(r"(\d+)\s*p(?:\b|\()", norm):
        piece_counts.add(int(value))

    bracket_parse_failed = has_bracket_piece_notation and len(piece_counts) == 0
    return piece_counts, outer_set_counts, has_bracket_piece_notation, bracket_parse_failed


def _extract_person_counts(norm: str) -> Set[int]:
    return set(int(x) for x in re.findall(r"(\d+)\s*인(?:용|조)?", norm))


def _extract_years(norm: str) -> Set[int]:
    return set(int(y) for y in re.findall(r"(19\d{2}|20\d{2})(?:년)?", norm))


def _tokenize_for_core(norm: str) -> List[str]:
    # 붙여쓰기/숫자 후행 대응: "필드플라워1" 형태를 유지
    return re.findall(r"[가-힣a-zA-Z]+\d+|[가-힣a-zA-Z]+|\d+", norm)


def _detect_item_types(text_no_space: str) -> Set[str]:
    found: Set[str] = set()
    # 긴 alias 우선 매칭 (뚜껑머그세트 vs 머그세트 충돌 방지)
    aliases = []
    for item_type, words in ITEM_TYPE_GROUPS.items():
        for w in words:
            aliases.append((item_type, w.replace(" ", "")))
    aliases.sort(key=lambda x: len(x[1]), reverse=True)

    for item_type, alias in aliases:
        if alias and alias in text_no_space:
            found.add(item_type)
    return found


def _extract_shape_tokens(tokens: List[str], text_no_space: str) -> Set[str]:
    found = set()
    for shape in SHAPE_TOKENS:
        if shape in text_no_space or shape in tokens:
            found.add(shape)
    return found


def _build_alias_list() -> List[str]:
    aliases = {a.replace(" ", "") for v in ITEM_TYPE_GROUPS.values() for a in v}
    return sorted(aliases, key=len, reverse=True)


def extract_features(name: str) -> NameFeatures:
    norm = normalize_text(name)
    text_no_space = norm.replace(" ", "")

    piece_counts, outer_set_counts, has_bracket_piece_notation, bracket_parse_failed = _extract_piece_info(norm)
    person_counts = _extract_person_counts(norm)
    years = _extract_years(norm)
    item_type_tokens = _detect_item_types(text_no_space)

    raw_tokens = _tokenize_for_core(norm)
    shape_tokens = _extract_shape_tokens(raw_tokens, text_no_space)

    noise_tokens: Set[str] = set()
    core_tokens: List[str] = []
    design_number_tokens: Set[str] = set()

    item_alias_list = _build_alias_list()

    for idx, token in enumerate(raw_tokens):
        token_no_space = token.replace(" ", "")

        numeric_design = re.match(r"^([가-힣a-zA-Z]+)(\d+)$", token_no_space)
        if numeric_design:
            design_number_tokens.add(f"{numeric_design.group(1)}#{numeric_design.group(2)}")

        if token_no_space in NOISE_TOKENS:
            noise_tokens.add(token_no_space)
            continue
        if token_no_space.isdigit():
            continue
        if token_no_space == "p":
            continue
        if token_no_space in shape_tokens:
            continue

        # 붙여쓰기 분해: 품목 alias를 토큰 내부에서 제거하고 남은 부분을 디자인 후보로 사용
        reduced = token_no_space
        for alias in item_alias_list:
            if alias in reduced:
                reduced = reduced.replace(alias, " ")

        reduced = re.sub(r"\d+", " ", reduced)
        reduced = re.sub(r"\s+", " ", reduced).strip()

        if not reduced:
            continue

        for part in reduced.split():
            if part in NOISE_TOKENS:
                noise_tokens.add(part)
                continue
            if part in shape_tokens:
                continue

            if len(part) == 1:
                if part in ONE_CHAR_DESIGN_TOKENS:
                    core_tokens.append(part)
                    continue
                if idx == 0 and re.fullmatch(r"[가-힣]", part):
                    core_tokens.append(part)
                    continue
                continue

            core_tokens.append(part)

    design_candidate_tokens = set(core_tokens)

    return NameFeatures(
        normalized=norm,
        clean_text=" ".join(core_tokens),
        core_tokens=core_tokens,
        design_candidate_tokens=design_candidate_tokens,
        shape_tokens=shape_tokens,
        item_type_tokens=item_type_tokens,
        noise_tokens=noise_tokens,
        piece_counts=piece_counts,
        person_counts=person_counts,
        outer_set_counts=outer_set_counts,
        has_bracket_piece_notation=has_bracket_piece_notation,
        bracket_parse_failed=bracket_parse_failed,
        years=years,
        design_number_tokens=design_number_tokens,
    )


def _core_similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return SequenceMatcher(None, " ".join(tokens_a), " ".join(tokens_b)).ratio()


def _similar_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 2 or len(b) < 2:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.80


def _numeric_suffix_conflict(base_number_tokens: Set[str], cand_number_tokens: Set[str]) -> bool:
    """필드플라워1 vs 필드플라워2 같은 숫자 후행 충돌 탐지."""
    if not base_number_tokens or not cand_number_tokens:
        return False

    def split_key(key: str):
        root, num = key.split("#", 1)
        return root, num

    base_map = {}
    for k in base_number_tokens:
        r, n = split_key(k)
        base_map.setdefault(r, set()).add(n)

    cand_map = {}
    for k in cand_number_tokens:
        r, n = split_key(k)
        cand_map.setdefault(r, set()).add(n)

    for root in set(base_map.keys()) & set(cand_map.keys()):
        if base_map[root] != cand_map[root]:
            return True
    return False


def _has_design_overlap(base_tokens: Set[str], cand_tokens: Set[str]) -> bool:
    if not base_tokens or not cand_tokens:
        return False
    if base_tokens & cand_tokens:
        return True

    for b in base_tokens:
        for c in cand_tokens:
            if len(b) >= 2 and len(c) >= 2 and (b in c or c in b):
                return True
            if _similar_word(b, c):
                return True
    return False


def _item_type_compatible(base_types: Set[str], cand_types: Set[str]) -> bool:
    if not base_types:
        return True

    if (base_types & STRICT_ITEM_REQUIRED) and not cand_types:
        return False

    if not cand_types:
        return True

    for b in base_types:
        for c in cand_types:
            if (b, c) in ALLOWED_ITEM_PAIR:
                return True
    return False


def _structure_match_strength(base: NameFeatures, cand: NameFeatures) -> int:
    """
    세트 구조 일치 강도 점수:
    - 디자인 일치
    - 품목 근접
    - 피스/인원 일치
    """
    score = 0
    if _has_design_overlap(base.design_candidate_tokens, cand.design_candidate_tokens):
        score += 2
    if _item_type_compatible(base.item_type_tokens, cand.item_type_tokens):
        score += 2
    if base.piece_counts and cand.piece_counts and (base.piece_counts & cand.piece_counts):
        score += 1
    if base.person_counts and cand.person_counts and (base.person_counts & cand.person_counts):
        score += 1
    return score


def evaluate_match(base_name: str, candidate_name: str, threshold: float = 0.42) -> Tuple[bool, str, float]:
    global EVALUATE_MATCH_CALL_COUNT
    EVALUATE_MATCH_CALL_COUNT += 1

    base = extract_features(base_name)
    cand = extract_features(candidate_name)

    if cand.bracket_parse_failed:
        return False, "괄호형 피스 표기 해석 실패", 0.0

    # 달력접시 연도 강규칙
    if "calendar_dish" in base.item_type_tokens and base.years and cand.years and not (base.years & cand.years):
        return False, "숫자/후행 토큰 불일치", 0.0

    # 디자인 후보 규칙
    if _numeric_suffix_conflict(base.design_number_tokens, cand.design_number_tokens):
        return False, "숫자/후행 토큰 불일치", 0.0

    design_mismatch = False
    if base.design_candidate_tokens and cand.design_candidate_tokens:
        if not _has_design_overlap(base.design_candidate_tokens, cand.design_candidate_tokens):
            design_mismatch = True
    elif base.design_candidate_tokens and not cand.design_candidate_tokens:
        return False, "오탈자/붙여쓰기 변형 흡수 실패", 0.0

    # 쉐입 규칙: 없음은 조건부 허용, 다름은 강탈락
    shape_mismatch = False
    if base.shape_tokens and cand.shape_tokens:
        if not (base.shape_tokens & cand.shape_tokens):
            shape_mismatch = True

    if design_mismatch and shape_mismatch:
        return False, "디자인/쉐입 둘 다 불일치", 0.0
    if design_mismatch:
        return False, "디자인 후보 불일치", 0.0
    if shape_mismatch:
        return False, "쉐입 불일치", 0.0

    # 세부 품목 타입 규칙
    if not _item_type_compatible(base.item_type_tokens, cand.item_type_tokens):
        if (base.item_type_tokens & STRICT_ITEM_REQUIRED) and not cand.item_type_tokens:
            return False, "쉐입 없음 후보 허용 실패", 0.0
        return False, "세부 품목 타입 불일치", 0.0

    # 기준에 쉐입 있고 후보에 쉐입이 없으면 추가 조건 필요(기존보다 완화)
    if base.shape_tokens and not cand.shape_tokens:
        strong_design_ok = _has_design_overlap(base.design_candidate_tokens, cand.design_candidate_tokens)
        near_item_ok = bool(base.item_type_tokens & cand.item_type_tokens) if cand.item_type_tokens else False
        piece_or_person_ok = False
        if base.piece_counts and cand.piece_counts and (base.piece_counts & cand.piece_counts):
            piece_or_person_ok = True
        elif base.person_counts and cand.person_counts and (base.person_counts & cand.person_counts):
            piece_or_person_ok = True

        # 완화 포인트:
        # - 디자인 강일치 + 품목 근접이면 piece/person 중 하나가 비어 있어도 허용
        if not (strong_design_ok and near_item_ok and (piece_or_person_ok or not (base.piece_counts and base.person_counts))):
            return False, "쉐입 없음 후보 허용이 너무 보수적", 0.0

    # 피스 규칙
    if base.piece_counts and cand.piece_counts and not (base.piece_counts & cand.piece_counts):
        if max(base.piece_counts) >= HIGH_VOLUME_PIECE_THRESHOLD:
            return False, "대피스/소피스 차이", 0.0
        return False, "피스 수 불일치", 0.0

    # 피스 없는 후보 조건부 허용
    if base.piece_counts and not cand.piece_counts:
        # 같은 품목 + 디자인 강일치면 허용 (연리지 단반상기 등)
        design_ok = _has_design_overlap(base.design_candidate_tokens, cand.design_candidate_tokens)
        item_ok = _item_type_compatible(base.item_type_tokens, cand.item_type_tokens)
        if not (design_ok and item_ok):
            return False, "붙여쓰기 분해 부족", 0.0
        # 대피스 상품은 피스 없는 후보에 보수적으로
        if max(base.piece_counts) >= HIGH_VOLUME_PIECE_THRESHOLD:
            return False, "대피스/소피스 차이", 0.0
        # 피스 없는 후보 특례: 구조가 강하게 맞으면 유사도 단계를 우회 허용
        return True, "통과", 1.0

    similarity = _core_similarity(base.core_tokens, cand.core_tokens)
    structure_score = _structure_match_strength(base, cand)

    # 홈세트/반상기/세트류는 구조 일치 시 threshold 완화
    threshold_adjusted = threshold
    if base.item_type_tokens & {"home_set", "bansang", "single_bansang", "coffee_set", "coffee_cup_set", "tea_set"}:
        if structure_score >= 4:
            threshold_adjusted = max(0.28, threshold - 0.12)
        elif structure_score >= 3:
            threshold_adjusted = max(0.34, threshold - 0.06)

    if similarity < threshold_adjusted:
        if structure_score >= 3:
            return False, "세트 구조 일치했지만 threshold 부족", similarity
        return False, "세부 품목 타입이 너무 보수적", similarity

    return True, "통과", similarity


def is_match(base_name: str, candidate_name: str, threshold: float = 0.42) -> bool:
    ok, _, _ = evaluate_match(base_name, candidate_name, threshold)
    return ok


def reset_evaluate_match_counter() -> None:
    """run_search 시작 시 호출하여 카운터를 초기화합니다."""
    global EVALUATE_MATCH_CALL_COUNT
    EVALUATE_MATCH_CALL_COUNT = 0


def get_evaluate_match_counter() -> int:
    """현재 evaluate_match 누적 호출 횟수를 반환합니다."""
    return EVALUATE_MATCH_CALL_COUNT
