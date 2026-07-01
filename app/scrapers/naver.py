"""네이버 지도 스크래퍼 (임베드 상태 파싱 방식).

pcmap.place.naver.com 목록 페이지를 실제 브라우저(헤드풀)로 열면, 결과가
페이지의 window.__APOLLO_STATE__ 에 구조화되어 박혀 있다. graphql XHR 은
인터셉트가 어렵고(첫 페이지는 XHR 이 아님) anti-bot 에 걸리기 쉬우므로,
DOM 이 렌더한 이 임베드 상태를 직접 파싱한다.

목록은 '안쪽' 스크롤 컨테이너에서 페이지네이션되므로, 내부 컨테이너를 끝까지
스크롤해 더 많은 항목을 __APOLLO_STATE__ 로 로드한 뒤 한 번에 추출한다.

APOLLO 아이템 필드(실측): name, x(lng), y(lat), category, roadAddress,
    visitorReviewScore(별점, 없으면 null), visitorReviewCount, blogCafeReviewCount
"""
from __future__ import annotations

from typing import Dict, List
from urllib.parse import quote

from .base import BaseScraper
from ..geo import Tile, point_in_polygon
from ..models import Place

_LIST_URL = "https://pcmap.place.naver.com/restaurant/list?query={q}"

# 페이지 안에서 실제로 스크롤되는 내부 컨테이너를 찾아 맨 아래로 내린다.
_SCROLL_INNER_JS = """
() => {
  const cands = Array.from(document.querySelectorAll('div, ul, section'));
  let best = null, bestScore = 0;
  for (const el of cands) {
    const oy = getComputedStyle(el).overflowY;
    if ((oy === 'auto' || oy === 'scroll') &&
        el.scrollHeight > el.clientHeight + 200) {
      const score = el.scrollHeight + el.querySelectorAll('li').length * 1000;
      if (score > bestScore) { bestScore = score; best = el; }
    }
  }
  if (best) best.scrollTop = best.scrollHeight;
  else window.scrollTo(0, document.body.scrollHeight);
}
"""

# window.__APOLLO_STATE__ 에서 목록 아이템(좌표+평점 포함) 추출.
_EXTRACT_JS = """
() => {
  const st = window.__APOLLO_STATE__ || {};
  const out = [];
  for (const k of Object.keys(st)) {
    const v = st[k];
    if (v && typeof v === 'object' && v.x != null && v.y != null && v.name
        && /BusinessesItem/i.test(k)) {
      out.push({
        id: String(v.id || k.split(':')[1] || k),
        name: v.name, x: v.x, y: v.y,
        category: v.category || '',
        roadAddress: v.roadAddress || v.commonAddress || v.address || '',
        visitorReviewScore: v.visitorReviewScore,
        visitorReviewCount: v.visitorReviewCount,
        blogCafeReviewCount: v.blogCafeReviewCount,
        totalReviewCount: v.totalReviewCount,
      });
    }
  }
  return out;
}
"""


class NaverScraper(BaseScraper):
    source = "naver"

    async def collect(self, context, tiles: List[Tile], terms: List[str], poly,
                      limit: int, fetch_all: bool, hard_cap: int) -> List[Place]:
        timeout = int(self.scrape_cfg.get("nav_timeout_ms", 15000))
        target = hard_cap if fetch_all else max(limit, 20)
        scrolls = 12 if fetch_all else 6

        page = await context.new_page()
        found: Dict[str, Place] = {}
        try:
            # warmup: 쿠키/세션 확보 (봇 탐지 완화)
            try:
                await page.goto("https://map.naver.com/", wait_until="domcontentloaded",
                                timeout=timeout)
                await page.wait_for_timeout(1200)
            except Exception:
                pass

            for term in terms:
                for attempt in range(2):  # 빈 결과면 1회 재시도
                    n_before = len(found)
                    await self._search_term(page, term, poly, found, timeout, scrolls)
                    if len(found) > n_before:
                        break
                    await page.wait_for_timeout(1500)
                await self.polite_wait()
                if not fetch_all and len(found) >= target:
                    break
        finally:
            await page.close()
        return list(found.values())

    async def _search_term(self, page, term, poly, found, timeout, scrolls) -> None:
        url = _LIST_URL.format(q=quote(term))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_timeout(3000)
        except Exception:
            return

        # 내부 컨테이너를 반복 스크롤해 더 많은 항목을 로드
        for _ in range(scrolls):
            try:
                await page.evaluate(_SCROLL_INNER_JS)
            except Exception:
                pass
            await page.wait_for_timeout(1100)

        try:
            items = await page.evaluate(_EXTRACT_JS)
        except Exception:
            items = []

        for it in items:
            p = self._parse_item(it, term)
            if p and point_in_polygon(poly, p.lng, p.lat):
                found.setdefault(p.key(), p)

    def _parse_item(self, it: dict, term: str):
        lng = self._to_float(it.get("x"))
        lat = self._to_float(it.get("y"))
        pid = str(it.get("id") or "")
        if lng is None or lat is None or not pid:
            return None

        review = self._to_int(it.get("visitorReviewCount")) + \
            self._to_int(it.get("blogCafeReviewCount"))
        if review == 0:
            review = self._to_int(it.get("totalReviewCount"))

        return Place(
            source=self.source,
            place_id=pid,
            name=it.get("name", ""),
            lat=lat,
            lng=lng,
            category=it.get("category", "") or "",
            matched_category=term,
            road_address=it.get("roadAddress", "") or "",
            url=f"https://map.naver.com/p/entry/place/{pid}",
            rating=self._to_float(it.get("visitorReviewScore")),
            review_count=review,
        )
