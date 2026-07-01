# 🍜 맛집 검색기 (matjip)

지도에서 영역을 직접 그리고, 카테고리·평점·리뷰수 조건으로 그 안의 맛집만
추출해 웹 테이블 + 지도 마커로 보여주는 **로컬 실행용** 도구.

- 언어: Python (Flask)
- 지도/그리기: Leaflet + Leaflet.draw + OpenStreetMap (API 키 불필요)
- 수집: playwright 스크래핑 (카카오맵 / 네이버지도)
- DB: 사용 안 함 (매번 실시간 수집)
- 설정: `config/*.yaml` 파일로 관리

## 동작 흐름

```
지도에서 다각형/사각형 그림 → GeoJSON
  → bbox 계산 → 격자(grid) 타일로 분할
  → 타일마다 카카오/네이버에 사각(rect/boundary) 검색
  → 결과 좌표를 원래 다각형 안에 있는지 판정(point-in-polygon)
  → 카카오는 상세 스크래핑으로 평점/리뷰 보강
  → 평점/리뷰/카테고리 필터 → 개수 제한 → 테이블 + 마커
```

소스(카카오/네이버)는 임의의 다각형을 못 받으므로, **검색은 사각형 단위로 하고
필터링은 다각형 단위**로 해서 그린 모양 그대로 걸러냅니다.

## 설치

```bash
cd matjip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 비밀 설정(카카오 키 등)은 gitignore 되는 로컬 파일에 둔다
cp config/settings.local.yaml.example config/settings.local.yaml
# → config/settings.local.yaml 을 열어 카카오 REST 키를 채운다
```

## 실행

```bash
source .venv/bin/activate
python -m app.server
# http://127.0.0.1:5000
```

## 설정 파일

### `config/settings.yaml`
- `sources` : 카카오/네이버 on/off
- `collection.default_limit` : 검색 UI 개수 input 기본값
- `collection.hard_cap` : "모두 가져오기" 안전 상한
- `grid.tile_size_m` / `max_tiles` : 격자 촘촘함/최대 타일 수
- `scrape.*` : headless, 동시성, 요청 간 딜레이, cooldown (IP 블락 회피)
- `scrape.mock: true` : **네트워크 없이 가짜 데이터로 UI 전체 흐름 테스트**
- `kakao.rest_api_key` : 카카오 목록 검색용 REST 키 (무료 발급). 비우면 카카오 건너뜀.

### `config/filters.yaml`
- `categories` : 카테고리 목록과 실제 검색어(terms) 매핑
- `rating` : 소스별 기본 최소 평점 / 최소 리뷰수 / 미제공 포함 여부

## 실제 수집 관련 참고

- **네이버** (동작 확인됨): `pcmap.place.naver.com/restaurant/list` 를 **헤드풀
  브라우저**로 열고, 목록의 **안쪽 스크롤 컨테이너**를 스크롤해 항목을 로드한 뒤
  페이지에 박힌 `window.__APOLLO_STATE__` 를 파싱합니다. 별점(visitorReviewScore),
  방문자/블로그 리뷰수, 좌표를 얻습니다. 별점이 없는 곳(null)은 리뷰수로 필터됩니다.
  - ⚠️ **`scrape.headless: false` 필수** — 네이버가 헤드리스를 봇으로 차단합니다.
    실행 시 크롬 창이 잠깐 떴다가 자동으로 스크롤·닫힙니다(정상).
  - anti-bot 은 rate 기반이라 **짧은 시간에 과도하게 검색하면 일시 차단**됩니다.
    config 의 delay/cooldown 을 지키고, 차단되면 잠시 후 다시 시도하세요.
    쿠키는 `.browser_profile/` 에 유지되어 재실행 시 탐지가 완화됩니다.
- **카카오**: 목록은 `dapi.kakao.com` 키워드+rect 검색(REST 키 필요, WGS84 좌표),
  평점/리뷰는 상세 스크래핑으로 보강합니다.
  - ⚠️ 키가 있어도 **해당 앱에 '카카오맵(OPEN_MAP_AND_LOCAL)' 서비스가 켜져
    있어야** 합니다. 안 켜져 있으면 403. developers.kakao.com → 앱 → 제품 설정에서
    카카오맵을 활성화하세요.
- 소스 응답 구조는 언제든 바뀔 수 있습니다. 필드가 안 맞으면
  `app/scrapers/kakao.py`, `app/scrapers/naver.py` 의 파싱부만 조정하면 됩니다.

## 처음이라면

키/네트워크 없이 먼저 화면을 보고 싶으면 `settings.yaml` 에서 `scrape.mock: true`
로 켜고 실행 → 지도에서 사각형 그리고 검색하면 가짜 맛집이 테이블/마커로 뜹니다.
동작 확인 후 `mock: false` 로 되돌리고 실제 키를 넣으세요.
