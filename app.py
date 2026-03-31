import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import List

from flask import Flask, jsonify, render_template, request, send_file

from config import Config
from providers.naver_provider import NaverProvider
from services.comparison import ComparisonResult, compare_product_with_results
from services.excel_reader import BaseProduct, ExcelReadError, PriceDebugRow, load_base_products
from services.exporter import export_results_to_excel
from services.matcher import get_evaluate_match_counter, reset_evaluate_match_counter


app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config["SECRET_KEY"]

UPLOAD_DIR = Path(app.config["UPLOAD_DIR"])
RESULT_DIR = Path(app.config["RESULT_DIR"])

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

STATE = {
    "products": [],
    "results": [],
    "warnings": [],
    "price_debug_rows": [],
    "last_uploaded_file": None,
    "debug_summaries": [],
    "summary_counts": {},
}


def _build_providers() -> List:
    return [NaverProvider(Config)]


@app.get("/")
def index():
    return render_template("index.html", use_mock=Config.USE_MOCK)


@app.post("/upload")
def upload_excel():
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"ok": False, "message": "업로드 실패: 엑셀 파일을 선택해주세요."}), 400

        original_filename = file.filename or "(이름없음)"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"upload_{timestamp}.xlsx"

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        save_path = UPLOAD_DIR / filename

        app.logger.info("[UPLOAD] 원본 파일명: %s", original_filename)
        app.logger.info("[UPLOAD] 저장 경로: %s", save_path)

        file.save(save_path)
        app.logger.info("[UPLOAD] 저장 성공 여부: %s", save_path.exists())

        app.logger.info("[UPLOAD] 엑셀 읽기 시작")
        products, warnings, price_debug_rows, read_row_count = load_base_products(str(save_path))
        app.logger.info("[UPLOAD] 읽은 행 수: %s", read_row_count)

        STATE["products"] = products
        STATE["warnings"] = warnings
        STATE["results"] = []
        STATE["price_debug_rows"] = price_debug_rows
        STATE["last_uploaded_file"] = str(save_path)
        STATE["debug_summaries"] = []
        STATE["summary_counts"] = {}

        return jsonify(
            {
                "ok": True,
                "message": "업로드 성공",
                "product_count": len(products),
                "warnings": warnings,
                "price_debug_rows": [_price_debug_to_dict(d) for d in price_debug_rows],
                "products": [{"name": p.name, "online_discount_price": p.online_discount_price} for p in products],
            }
        )

    except ExcelReadError as e:
        app.logger.exception("[UPLOAD] ExcelReadError 발생")
        traceback.print_exc()
        return jsonify({"ok": False, "message": f"업로드 실패: {str(e)}"}), 400
    except Exception as e:
        app.logger.exception("[UPLOAD] 예기치 못한 예외 발생")
        traceback.print_exc()
        return jsonify({"ok": False, "message": f"업로드 실패: {str(e)}"}), 500


@app.post("/run-search")
def run_search():
    run_started_at = perf_counter()
    products: List[BaseProduct] = STATE["products"]
    if not products:
        return jsonify({"ok": False, "message": "먼저 엑셀을 업로드해주세요."}), 400

    providers = _build_providers()
    provider = providers[0]

    all_results: List[ComparisonResult] = []
    runtime_warnings: List[str] = list(STATE["warnings"])
    debug_summaries = []

    api_raw_zero_count = 0
    filtered_zero_count = 0
    rate_limit_product_count = 0

    app.logger.info("[RUN] 전체 품목 수=%s", len(products))
    reset_evaluate_match_counter()

    for product in products:
        search_started_at = perf_counter()
        search_results = provider.search(product.name)
        search_elapsed = perf_counter() - search_started_at
        raw_count = getattr(provider, "last_raw_count", len(search_results))
        pages_called = getattr(provider, "last_pages_called", 0)
        app.logger.info(
            "[PERF] product='%s' provider.search() 소요=%.3fs / raw 후보 개수=%s / pages=%s",
            product.name,
            search_elapsed,
            raw_count,
            pages_called,
        )

        provider_error = getattr(provider, "last_error_message", "")
        provider_error_type = getattr(provider, "last_error_type", "")
        if provider_error and provider_error not in runtime_warnings:
            runtime_warnings.append(provider_error)

        compare_started_at = perf_counter()
        product_results, debug_info = compare_product_with_results(product, search_results)
        compare_elapsed = perf_counter() - compare_started_at
        app.logger.info(
            "[PERF] product='%s' compare_product_with_results() 소요=%.3fs / evaluate 대상=%s",
            product.name,
            compare_elapsed,
            len(search_results),
        )

        # 상태성 행 생성 (검색 결과/필터 진단용)
        if provider_error_type == "API_RATE_LIMIT":
            rate_limit_product_count += 1
            product_results = [
                ComparisonResult(
                    base_product_name=product.name,
                    base_online_discount_price=product.online_discount_price,
                    found_product_name="-",
                    sale_price=None,
                    mall_name="-",
                    product_link="",
                    is_below_base=False,
                    shipping_fee_known=False,
                    status="API 429 / 호출 제한",
                    is_problem=True,
                )
            ]
        elif raw_count == 0:
            api_raw_zero_count += 1
            product_results = [
                ComparisonResult(
                    base_product_name=product.name,
                    base_online_discount_price=product.online_discount_price,
                    found_product_name="-",
                    sale_price=None,
                    mall_name="-",
                    product_link="",
                    is_below_base=False,
                    shipping_fee_known=False,
                    status="검색 결과 없음",
                    is_problem=False,
                )
            ]
            app.logger.warning("[DEBUG] API_RAW_ZERO / product=%s", product.name)
        elif raw_count > 0 and debug_info.passed_count == 0:
            filtered_zero_count += 1
            status_text = "매칭 실패"
            if debug_info.reasons.get("피스 수 불일치", 0) >= raw_count:
                status_text = "매칭 실패(피스 수 규칙)"
            elif debug_info.reasons.get("디자인명 불일치", 0) >= raw_count:
                status_text = "매칭 실패(디자인명 규칙)"
            product_results = [
                ComparisonResult(
                    base_product_name=product.name,
                    base_online_discount_price=product.online_discount_price,
                    found_product_name="-",
                    sale_price=None,
                    mall_name="-",
                    product_link="",
                    is_below_base=False,
                    shipping_fee_known=False,
                    status=status_text,
                    is_problem=False,
                )
            ]
            app.logger.warning("[DEBUG] FILTERED_TO_ZERO / product=%s / reasons=%s", product.name, debug_info.reasons)

        all_results.extend(product_results)

        debug_summaries.append(
            {
                "product_name": product.name,
                "raw_count": raw_count,
                "passed_count": debug_info.passed_count,
                "dropped_count": max(raw_count - debug_info.passed_count, 0),
                "pages_called": pages_called,
                "accumulated_raw_count": raw_count,
                "reasons": debug_info.reasons,
                "piece_rule_all_dropped": (
                    raw_count > 0
                    and debug_info.passed_count == 0
                    and debug_info.reasons.get("피스 수 불일치", 0) >= raw_count
                ),
            }
        )

    # 기준제품명 단위 정렬(그룹핑 표시에 유리)
    all_results.sort(key=lambda x: (x.base_product_name, x.found_product_name))

    # 화면 상단 요약
    grouped = {}
    for row in all_results:
        grouped.setdefault(row.base_product_name, set()).add(row.status)

    summary_counts = {
        "problem_products": sum(1 for _, st in grouped.items() if "가격 문제 있음" in st),
        "rate_limit_products": sum(1 for _, st in grouped.items() if "API 429 / 호출 제한" in st),
        "no_result_products": sum(1 for _, st in grouped.items() if "검색 결과 없음" in st),
    }

    # 운영 로그
    app.logger.info("[RUN] 실제 네이버 API 호출 수=%s", provider.api_call_count)
    app.logger.info("[RUN] 429 발생 횟수=%s", provider.rate_limit_count)
    app.logger.info("[RUN] 재시도 횟수=%s", provider.retry_count)
    app.logger.info("[RUN] API_RAW_ZERO 개수=%s", api_raw_zero_count)
    app.logger.info("[RUN] FILTERED_TO_ZERO 개수=%s", filtered_zero_count)
    app.logger.info("[PERF] evaluate_match 호출 횟수=%s", get_evaluate_match_counter())
    app.logger.info("[PERF] run_search 총 소요=%.3fs", perf_counter() - run_started_at)

    STATE["results"] = all_results
    STATE["warnings"] = runtime_warnings
    STATE["debug_summaries"] = debug_summaries
    STATE["summary_counts"] = summary_counts

    return jsonify(
        {
            "ok": True,
            "count": len(all_results),
            "results": [_result_to_dict(r) for r in all_results],
            "warnings": runtime_warnings,
            "debug_summaries": debug_summaries,
            "summary_counts": summary_counts,
            "mode": "MOCK MODE" if Config.USE_MOCK else "REAL MODE",
        }
    )


@app.get("/results")
def get_results():
    # 기본값: 문제 결과만 보기
    show_all = request.args.get("show_all", "false").lower() == "true"
    results: List[ComparisonResult] = STATE["results"]

    if not show_all:
        results = [r for r in results if r.is_problem]

    return jsonify(
        {
            "ok": True,
            "count": len(results),
            "results": [_result_to_dict(r) for r in results],
            "debug_summaries": STATE.get("debug_summaries", []),
            "summary_counts": STATE.get("summary_counts", {}),
        }
    )


@app.get("/download")
def download_excel():
    results: List[ComparisonResult] = STATE["results"]
    if not results:
        return jsonify({"ok": False, "message": "다운로드할 결과가 없습니다."}), 400

    # 기본: 문제 결과만 엑셀 다운로드
    show_all = request.args.get("show_all", "false").lower() == "true"
    excel_io = export_results_to_excel(results, only_problem=not show_all)
    return send_file(
        excel_io,
        as_attachment=True,
        download_name="price_monitor_result.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _result_to_dict(r: ComparisonResult):
    return {
        "base_product_name": r.base_product_name,
        "base_online_discount_price": r.base_online_discount_price,
        "found_product_name": r.found_product_name,
        "sale_price": r.sale_price,
        "mall_name": r.mall_name,
        "product_link": r.product_link,
        "is_below_base": r.is_below_base,
        "shipping_fee_known": r.shipping_fee_known,
        "status": r.status,
        "is_problem": r.is_problem,
    }


def _price_debug_to_dict(d: PriceDebugRow):
    return {
        "row_number": d.row_number,
        "product_name": d.product_name,
        "raw_price_value": d.raw_price_value,
        "cleaned_price_value": d.cleaned_price_value,
        "parsed_price": d.parsed_price,
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
