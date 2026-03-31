import os


class Config:
    """앱 전역 설정값을 보관합니다."""

    USE_MOCK = os.getenv("USE_MOCK", os.getenv("MOCK_MODE", "false")).lower() == "true"

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "sample_data/uploads")
    RESULT_DIR = os.getenv("RESULT_DIR", "sample_data/results")

    NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
    NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

    NAVER_DISPLAY_COUNT = int(os.getenv("NAVER_DISPLAY_COUNT", "100"))
    NAVER_MAX_PAGES = int(os.getenv("NAVER_MAX_PAGES", "3"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

    NAVER_REQUEST_DELAY_MS = int(os.getenv("NAVER_REQUEST_DELAY_MS", "500"))
    NAVER_MAX_RETRIES = int(os.getenv("NAVER_MAX_RETRIES", "3"))
    NAVER_BACKOFF_BASE_SECONDS = float(os.getenv("NAVER_BACKOFF_BASE_SECONDS", "1"))


    # 검색어 보강용 브랜드 prefix 목록 (콤마로 여러 개 지정 가능)
    # 예: SEARCH_BRAND_PREFIXES="한국도자기,브랜드B"
    _brand_prefix_raw = os.getenv("SEARCH_BRAND_PREFIXES", "한국도자기")
    SEARCH_BRAND_PREFIXES = [x.strip() for x in _brand_prefix_raw.split(",") if x.strip()]
