"""카카오맵 스크래퍼.

전략(소스 레벨 하이브리드):
  1) 목록: dapi.kakao.com 키워드 검색을 rect(사각 범위)로 호출 → WGS84 좌표.
     (REST 키 필요. config/settings.yaml 의 kakao.rest_api_key 에 넣는다. 무료 발급)
  2) 평점/리뷰: place.map.kakao.com 상세를 스크래핑해서 별점·리뷰수 보강(enrich).
     → 평점 데이터 자체는 '스크래핑'으로 확보하므로 별점 필터가 정상 동작한다.

REST 키가 없으면 목록을 못 가져오므로 빈 결과를 반환하고 서버 로그에 안내한다.
상세 JSON 스키마는 바뀔 수 있으니 _parse_detail 을 조정하면 된다.
"""
from __future__ import annotations

import asyncio
from typing import List
from urllib.parse import quote

from .base import BaseScraper
from .. import progress
from ..geo import Tile
from ..models import Place

_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"
# 상세(평점/리뷰) 엔드포인트. appversion/pf/Origin 헤더가 없으면 406.
_DETAIL = "https://place-api.map.kakao.com/places/panel3/{pid}"


class KakaoScraper(BaseScraper):
    source = "kakao"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.rest_key = (settings.get("kakao", {}) or {}).get("rest_api_key", "").strip()
        self.warned = False

    async def search_wait(self) -> None:
        # dapi 는 공식 REST API(IP 블락 대상 아님) → 최소 딜레이만 (rate limit 존중)
        await asyncio.sleep(0.08)

    async def search_tile(self, context, tile: Tile, term: str) -> List[Place]:
        if not self.rest_key:
            if not self.warned:
                print("[kakao] REST 키가 없습니다 → config/settings.yaml 의 "
                      "kakao.rest_api_key 를 설정하세요. (카카오 소스 건너뜀)")
                self.warned = True
            return []

        rect = f"{tile.min_lng},{tile.min_lat},{tile.max_lng},{tile.max_lat}"
        headers = {
            "Authorization": f"KakaoAK {self.rest_key}",
            "User-Agent": self.scrape_cfg.get("user_agent", ""),
        }
        timeout = int(self.scrape_cfg.get("nav_timeout_ms", 15000))

        out: List[Place] = []
        for page in range(1, 4):  # dapi 는 rect 당 최대 45개(15 * 3page)
            url = f"{_KEYWORD}?query={quote(term)}&rect={rect}&size=15&page={page}"
            try:
                resp = await context.request.get(url, headers=headers, timeout=timeout)
                if not resp.ok:
                    break
                data = await resp.json()
            except Exception:
                break

            for doc in data.get("documents", []):
                p = self._parse_doc(doc, term)
                if p:
                    out.append(p)

            if data.get("meta", {}).get("is_end", True):
                break
        return out

    def _parse_doc(self, doc: dict, term: str):
        lng = self._to_float(doc.get("x"))
        lat = self._to_float(doc.get("y"))
        pid = str(doc.get("id") or "")
        if lng is None or lat is None or not pid:
            return None
        return Place(
            source=self.source,
            place_id=pid,
            name=doc.get("place_name", ""),
            lat=lat,
            lng=lng,
            category=doc.get("category_name", "") or "",
            matched_category=term,
            address=doc.get("address_name", "") or "",
            road_address=doc.get("road_address_name", "") or "",
            phone=doc.get("phone", "") or "",
            url=doc.get("place_url", f"https://place.map.kakao.com/{pid}"),
            rating=None,        # enrich 에서 채움
            review_count=0,
        )

    async def enrich(self, context, places: List[Place]) -> None:
        """상세 페이지에서 별점/리뷰수를 채운다(제자리 수정)."""
        if not places:
            return
        headers = {
            "User-Agent": self.scrape_cfg.get("user_agent", ""),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR",
            "Referer": "https://place.map.kakao.com/",
            "Origin": "https://place.map.kakao.com",
            "appversion": "6.6.0",   # 이 헤더 없으면 406
            "pf": "PC",
        }
        timeout = int(self.scrape_cfg.get("nav_timeout_ms", 15000))
        total = len(places)
        # dapi/place-api 는 공식 API → 동시 요청 안전. 순차(≈90s) 대신 병렬로 대폭 단축.
        concurrency = int(self.scrape_cfg.get("enrich_concurrency", 8))
        sem = asyncio.Semaphore(max(1, concurrency))
        progress.update(phase="카카오 평점 보강", done=0, total=total)
        done = 0

        async def one(p):
            nonlocal done
            async with sem:
                url = _DETAIL.format(pid=p.place_id)
                try:
                    resp = await context.request.get(url, headers=headers, timeout=timeout)
                    if resp.ok:
                        self._parse_detail(await resp.json(), p)
                except Exception:
                    pass
            done += 1
            if done % 15 == 0 or done == total:
                print(f"[kakao] 평점 보강 {done}/{total}", flush=True)
                progress.update(done=done)

        await asyncio.gather(*[one(p) for p in places])

    def _parse_detail(self, data: dict, p: Place) -> None:
        data = data or {}
        # 카카오맵 별점 + '후기'(평점 있는 리뷰) 수만 사용.
        # 블로그 리뷰는 평점이 없으므로 리뷰수에서 제외한다. (예: 후기 3 · 블로그 17 → 3)
        score_set = (data.get("kakaomap_review", {}) or {}).get("score_set", {}) or {}
        p.rating = self._to_float(score_set.get("average_score"))
        p.review_count = self._to_int(score_set.get("review_count"))
