import os


class Config:
    """앱 전역 설정값을 보관합니다."""

    USE_MOCK = os.getenv("USE_MOCK", os.getenv("MOCK_MODE", "false")).lower() == "true"

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "sample_data/uploads")
    RESULT_DIR = os.getenv("RESULT_DIR", "sample_data/results")

    NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
    NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

    SEARCH_SPEED_MODE = os.getenv("SEARCH_SPEED_MODE", "safe_fast").strip().lower()

    # 실행 완료 보장용 fail-safe
    MAX_SECONDS_PER_PRODUCT = int(os.getenv("MAX_SECONDS_PER_PRODUCT", "30"))
    MAX_SECONDS_PER_RUN = int(os.getenv("MAX_SECONDS_PER_RUN", "180"))
    MAX_MATCH_EVALUATION_CANDIDATES = int(os.getenv("MAX_MATCH_EVALUATION_CANDIDATES", "20"))

    # safe_fast 기본값 (사용자가 환경변수로 덮어쓰기 가능)
    _default_display_count = "20" if SEARCH_SPEED_MODE == "safe_fast" else "100"
    _default_max_pages = "2" if SEARCH_SPEED_MODE == "safe_fast" else "3"
    _default_request_timeout = "5" if SEARCH_SPEED_MODE == "safe_fast" else "10"
    _default_request_delay_ms = "200" if SEARCH_SPEED_MODE == "safe_fast" else "500"
    _default_max_retries = "2" if SEARCH_SPEED_MODE == "safe_fast" else "3"
    _default_backoff_seconds = "0.5" if SEARCH_SPEED_MODE == "safe_fast" else "1"
    _default_max_query_candidates = "6" if SEARCH_SPEED_MODE == "safe_fast" else "6"
    # safe_fast에서도 첫 query 결과만으로 너무 빨리 끝내지 않기 위한 최소 query 시도 횟수
    _default_min_queries_to_try = "3" if SEARCH_SPEED_MODE == "safe_fast" else "1"

    NAVER_DISPLAY_COUNT = int(os.getenv("NAVER_DISPLAY_COUNT", _default_display_count))
    NAVER_MAX_PAGES = int(os.getenv("NAVER_MAX_PAGES", _default_max_pages))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", _default_request_timeout))

    NAVER_REQUEST_DELAY_MS = int(os.getenv("NAVER_REQUEST_DELAY_MS", _default_request_delay_ms))
    NAVER_MAX_RETRIES = int(os.getenv("NAVER_MAX_RETRIES", _default_max_retries))
    NAVER_BACKOFF_BASE_SECONDS = float(os.getenv("NAVER_BACKOFF_BASE_SECONDS", _default_backoff_seconds))
    NAVER_MAX_QUERY_CANDIDATES = int(os.getenv("NAVER_MAX_QUERY_CANDIDATES", _default_max_query_candidates))
    NAVER_MIN_QUERIES_TO_TRY = int(os.getenv("NAVER_MIN_QUERIES_TO_TRY", _default_min_queries_to_try))


    # 검색어 보강용 브랜드 prefix 목록 (콤마로 여러 개 지정 가능)
    # 예: SEARCH_BRAND_PREFIXES="한국도자기,브랜드B"
    _brand_prefix_raw = os.getenv("SEARCH_BRAND_PREFIXES", "한국도자기")
    SEARCH_BRAND_PREFIXES = [x.strip() for x in _brand_prefix_raw.split(",") if x.strip()]
