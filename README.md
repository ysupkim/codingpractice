# 사내용 가격 모니터링 웹앱 (MVP)

초보자도 바로 실행할 수 있는 **엑셀 업로드 → 검색 → 기준가 미만 확인 → 엑셀 다운로드** 흐름의 1차 버전입니다.

---

## 1) 프로젝트 구조

```text
codingpractice/
├─ app.py
├─ config.py
├─ requirements.txt
├─ README.md
├─ templates/
│  └─ index.html
├─ static/
│  ├─ style.css
│  └─ app.js
├─ providers/
│  ├─ base_provider.py
│  ├─ naver_provider.py
│  └─ todayhouse_provider.py
├─ services/
│  ├─ excel_reader.py
│  ├─ matcher.py
│  ├─ comparison.py
│  └─ exporter.py
└─ sample_data/
   └─ sample_discount_list.csv
```

---

## 2) 핵심 동작 요약

1. 엑셀 업로드
2. `품목`, `온라인할인가` 헤더가 있는 실제 표 시작 행 자동 탐지
3. 품목별 검색(provider)
   - Naver provider
   - TodayHouse provider
4. 매칭 규칙 적용
   - 핵심 제품명 유사 매칭
   - **세트 수량(2인/4인, 13P/21P) 반드시 일치**
5. 기준 온라인할인가와 비교
   - 가능하면 배송비 포함 총액 비교
   - 배송비 모르면 상품가만 비교 + "배송비 확인불가" 표시
6. 결과를 웹 표 + 엑셀(.xlsx)로 제공

---

## 3) 실행 방법 (초보자용)

### 3-1. 파이썬 준비
- Python 3.10+ 권장

### 3-2. 가상환경 생성/활성화

#### macOS / Linux
```bash
python -m venv .venv
source .venv/bin/activate
```

#### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3-3. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3-4. 앱 실행 (기본: REAL 모드)
```bash
python app.py
```

브라우저에서 `http://localhost:5000` 접속.

---

## 4) Mock mode / Real mode

### Mock mode
- `USE_MOCK=true`
- 외부 연동 없이 고정 샘플 데이터로 검색
- 데모/사내 설명/기능 테스트에 적합

### Real mode
- `USE_MOCK=false`
- Naver provider는 **네이버 검색 API 키**가 있으면 실제 호출
- TodayHouse provider는 현재 placeholder (정책/공식 API 이슈로 기본 빈 결과)
- REAL MODE에서 네이버 API 응답이 0건이면 0건 그대로 표시하며, mock 결과로 자동 대체하지 않습니다.

- **중요:** 직원은 웹 링크만 접속해서 사용하고, API 키(`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`)는 서버 실행 환경의 환경변수에만 보관합니다.

### 환경변수 예시

#### macOS / Linux
```bash
export USE_MOCK=false
export NAVER_CLIENT_ID=your_id
export NAVER_CLIENT_SECRET=your_secret
python app.py
```

#### Windows PowerShell
```powershell
$env:USE_MOCK="false"
$env:NAVER_CLIENT_ID="your_id"
$env:NAVER_CLIENT_SECRET="your_secret"
python app.py
```

---

## 5) 엑셀 입력 규칙

업로드 파일은 `.xlsx` 권장입니다.

필수 컬럼:
- `품목`
- `온라인할인가`

특징:
- 1행부터 고정 파싱하지 않음
- 안내문/빈 행이 있어도 실제 헤더 행 자동 탐지
- 온라인할인가가 비어있거나 숫자가 아니면 해당 행은 건너뛰고 경고 표시

---

## 6) 예외 처리

아래 상황을 처리합니다.

- 업로드 후 화면의 **가격 파싱 디버그 표**에서 `원본 가격 값`과 `정리된 가격 값` 확인 가능
- 빈 행/안내문 행 섞임
- 온라인할인가 비어 있음
- 온라인할인가 숫자 아님
- 검색 결과 없음
- 링크 없음
- 배송비 확인 불가

---

## 7) 플랫폼 추가 방법 (provider 확장)

1. `providers/new_platform_provider.py` 생성
2. `BaseProvider` 상속
3. `search(query)` 구현 후 `SearchResult` 리스트 반환
4. `app.py`의 `_build_providers()`에 추가

예시:
```python
from providers.new_platform_provider import NewPlatformProvider

def _build_providers():
    return [
        NaverProvider(Config),
        TodayHouseProvider(Config),
        NewPlatformProvider(Config),
    ]
```

---

## 8) 실제 운영 확장 포인트

- in-memory 상태(`STATE`)를 DB(SQLite/PostgreSQL)로 교체
- 배치 스케줄링(Celery/APScheduler) 추가
- 로그인/권한관리 추가
- 결과 중복 제거/정렬 고도화
- 플랫폼별 공식 API 연동 강화

---

## 9) 자주 나는 에러

1. `ModuleNotFoundError`
   - 원인: 패키지 미설치
   - 해결: `pip install -r requirements.txt`

2. `엑셀에서 '품목'/'온라인할인가' 헤더 행을 찾지 못했습니다`
   - 원인: 헤더명이 다름
   - 해결: 헤더 텍스트를 정확히 `품목`, `온라인할인가`로 맞춤

3. Real mode에서 결과가 거의 없거나 0건
   - 원인: API 키 미설정, 호출 제한, TodayHouse placeholder
   - 해결: 네이버 API 키 확인 / provider 교체 구현

---

## 10) 보안/운영 주의

- `SECRET_KEY`는 운영에서 반드시 변경하세요.
- 업로드 파일은 내부망에서만 처리하세요.
- 외부 사이트 이용약관/API 정책을 반드시 준수하세요.


## 11) 네이버 429 대응 (운영성)

- 네이버 API의 429는 하루/초당 호출 제한과 관련될 수 있습니다.
- 이를 위해 앱에 다음을 넣었습니다.
  - 요청 간 지연(`NAVER_REQUEST_DELAY_MS`)
  - 지수 백오프 재시도(`NAVER_MAX_RETRIES`, `NAVER_BACKOFF_BASE_SECONDS`)
  - 동일 query 실행 중 캐시(in-memory)
- 직원은 API 키를 몰라도 되고, 키는 서버 환경변수(`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`)에만 보관합니다.
- 검색 후보 보강을 위해 브랜드 prefix를 환경변수로 관리합니다: `SEARCH_BRAND_PREFIXES` (기본값: `한국도자기`, 여러 개는 콤마 구분).


## 12) 쇼핑몰명 안내 (판매자 컬럼 제거)

- 네이버 쇼핑 검색 API 응답은 `mallName`(쇼핑몰명)은 제공하지만, 실판매자를 안정적으로 분리하기 어렵습니다.
- 1차 버전 UI/엑셀에서는 혼동을 줄이기 위해 **판매자 컬럼을 제거**하고 쇼핑몰명 중심으로 제공합니다.
- 실판매자 분리는 플랫폼 상세페이지 추가 수집(별도 크롤링/제휴 API)이 필요합니다.



## 13) 매칭 로직(정확도 개선)

- `p`, `pc`, `pcs`, `piece`, `pieces`는 모두 같은 피스 표기로 통합합니다.
- `2(4)p`, `6(7)pcs` 같은 괄호형 표기는 **괄호 안 숫자**를 총 피스 수로 우선 해석합니다.
- `한국도자기`, `노원.중랑점`, `탑탑리빙`, `본차이나`, `특가` 같은 노이즈 토큰은 약하게 처리합니다.
- 디자인명(예: 로얄파일블루, 매난국죽, 실버리본, 라임, 연) 교집합이 없으면 매칭하지 않습니다.
- 품목 유형은 동의어 그룹(예: 커피세트/커피잔, 티셋/티세트, 홈세트/홈 세트)으로 비교합니다.

- 한 글자 디자인명 예외(예: `연`)를 보존하고, 경미한 철자 변형(예: 패일/페일)을 토큰 유사도로 보정합니다.
- 붙여쓰기 상품명에서도 품목/피스/인원을 탐지하도록 개선했습니다.
- 달력접시류는 연도(예: 2026 vs 2024) 불일치를 강하게 차단합니다.

## 16) 매칭 운영 팁 (세부 품목 타입)

- 최근 매칭에서는 세부 품목 타입을 더 촘촘히 분리합니다.
  - 예: `coffee_set`, `coffee_cup_set`, `coffee_cup_single`, `mug_set`, `lid_mug_set`, `bansang`, `calendar_dish`, `art_or_frame`, `vase`, `utensil_holder`
- 같은 디자인 토큰이 있어도 세부 품목 타입이 다르면 매칭을 차단합니다.
- 운영 중 오탐/미탐이 반복되면 `ITEM_TYPE_GROUPS`, `ALLOWED_ITEM_PAIR`, `NOISE_TOKENS`를 우선 업데이트하세요.

## 17) false negative 튜닝 메모

- 쉐입이 기준에만 있고 후보에 없을 때는, 디자인/품목/세트 구조가 강하게 맞으면 조건부 허용합니다.
- 피스가 없는 후보라도(예: `연리지 단반상기 6p` ↔ `연리지 단반상기`) 디자인+품목이 강일치하면 통과할 수 있습니다.
- 반대로 `lid_mug`, `vase`, `utensil_holder`, `art_or_frame` 계열은 품목 타입 불일치로 계속 차단합니다.
