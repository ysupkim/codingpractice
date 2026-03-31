from io import BytesIO
from typing import Iterable, List

import pandas as pd

from services.comparison import ComparisonResult


def export_results_to_excel(results: Iterable[ComparisonResult], only_problem: bool = True) -> BytesIO:
    filtered: List[ComparisonResult] = list(results)
    if only_problem:
        filtered = [r for r in filtered if r.is_problem or r.status == "API 429 / 호출 제한"]

    filtered.sort(key=lambda x: (x.base_product_name, x.found_product_name))

    rows = []
    for r in filtered:
        rows.append(
            {
                "기준 제품명": r.base_product_name,
                "기준 온라인할인가": r.base_online_discount_price,
                "검색 상품명": r.found_product_name,
                "판매가격": r.sale_price,
                "쇼핑몰명": r.mall_name,
                "링크": r.product_link,
                "상태": r.status,
            }
        )

    df = pd.DataFrame(rows)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="결과", index=False)
    output.seek(0)
    return output
