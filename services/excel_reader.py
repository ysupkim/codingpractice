from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import numbers
import re
from typing import List, Optional, Tuple

import pandas as pd


@dataclass
class BaseProduct:
    """엑셀에서 읽은 기준 상품 정보."""

    name: str
    online_discount_price: int


@dataclass
class PriceDebugRow:
    """디버그용 가격 파싱 로그."""

    row_number: int
    product_name: str
    raw_price_value: str
    cleaned_price_value: str
    parsed_price: Optional[int]


class ExcelReadError(Exception):
    pass


REQUIRED_HEADERS = ["품목", "온라인할인가"]


def _normalize_header(value: str) -> str:
    return str(value).strip().replace(" ", "")


def _find_header_row(df_raw: pd.DataFrame) -> Optional[int]:
    """
    '품목', '온라인할인가'가 모두 들어 있는 실제 헤더 행을 찾습니다.
    안내문/빈 행이 앞에 있어도 찾을 수 있도록 구현.
    """
    for row_idx in range(min(len(df_raw), 50)):
        row_values = [_normalize_header(v) for v in df_raw.iloc[row_idx].fillna("").tolist()]
        if "품목" in row_values and "온라인할인가" in row_values:
            return row_idx
    return None


def _safe_int_from_numeric(value) -> Optional[int]:
    """float 과학표기/부동소수 오차를 안전하게 정수로 변환."""
    if isinstance(value, bool):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        if not math.isfinite(float(value)):
            return None
        # 29399.999999999996 같은 값 보정
        return int(round(float(value)))
    return None


def _parse_price(value) -> Tuple[Optional[int], str, str]:
    """
    반환값: (파싱된 숫자, 원본문자열, 정리된문자열)
    """
    if pd.isna(value):
        return None, "", ""

    numeric = _safe_int_from_numeric(value)
    if numeric is not None:
        return numeric, str(value), str(numeric)

    raw_text = str(value).strip()
    cleaned_text = raw_text.replace(",", "").replace("원", "").strip()

    if cleaned_text == "":
        return None, raw_text, cleaned_text

    # 문자열이 숫자/소수/지수표기 형태면 Decimal로 정확 변환
    numeric_pattern = r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$"
    if re.match(numeric_pattern, cleaned_text):
        try:
            dec_value = Decimal(cleaned_text)
            return int(dec_value.to_integral_value(rounding="ROUND_HALF_UP")), raw_text, cleaned_text
        except (InvalidOperation, ValueError):
            return None, raw_text, cleaned_text

    # 혼합 문자열(예: '약 121,450원')에서는 첫 번째 숫자 토큰만 사용
    token_pattern = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
    token = re.search(token_pattern, cleaned_text)
    if token:
        token_text = token.group(0)
        try:
            dec_value = Decimal(token_text)
            parsed = int(dec_value.to_integral_value(rounding="ROUND_HALF_UP"))
            return parsed, raw_text, token_text
        except (InvalidOperation, ValueError):
            return None, raw_text, cleaned_text

    return None, raw_text, cleaned_text


def load_base_products(excel_path: str) -> Tuple[List[BaseProduct], List[str], List[PriceDebugRow], int]:
    """
    엑셀에서 기준 상품 목록을 읽어옵니다.
    반환: (정상 데이터 목록, 경고 메시지 목록, 가격 파싱 디버그 목록, 읽은 행 수)
    """
    df_raw = pd.read_excel(excel_path, header=None, engine="openpyxl")
    header_row = _find_header_row(df_raw)
    if header_row is None:
        raise ExcelReadError("엑셀에서 '품목'/'온라인할인가' 헤더 행을 찾지 못했습니다.")

    header_values = [str(v).strip() for v in df_raw.iloc[header_row].tolist()]
    df_data = df_raw.iloc[header_row + 1 :].copy()
    df_data.columns = header_values

    for col in REQUIRED_HEADERS:
        if col not in df_data.columns:
            raise ExcelReadError(f"필수 컬럼 누락: {col}")

    products: List[BaseProduct] = []
    warnings: List[str] = []
    debug_rows: List[PriceDebugRow] = []

    for idx, row in df_data.iterrows():
        raw_name = row.get("품목", "")
        name = str(raw_name).strip() if not pd.isna(raw_name) else ""

        if not name:
            continue

        price, raw_price, cleaned_price = _parse_price(row.get("온라인할인가"))
        excel_row_num = idx + 1

        debug_rows.append(
            PriceDebugRow(
                row_number=excel_row_num,
                product_name=name,
                raw_price_value=raw_price,
                cleaned_price_value=cleaned_price,
                parsed_price=price,
            )
        )

        if price is None:
            warnings.append(f"행 {excel_row_num}: 온라인할인가가 비어있거나 숫자가 아닙니다. ({name})")
            continue

        products.append(BaseProduct(name=name, online_discount_price=price))

    if not products:
        warnings.append("유효한 기준 상품이 없습니다. 엑셀 값을 확인해주세요.")

    return products, warnings, debug_rows, len(df_data)
