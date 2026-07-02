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

# 중심 좌표(x=lng, y=lat)를 넣으면 검색이 그 지역으로 localize 된다(실측).
# (없으면 전국 결과가 나와 대부분 폴리곤 밖으로 버려짐)
_LIST_URL = "https://pcmap.place.naver.com/restaurant/list?query={q}&x={x}&y={y}"

# 목록의 '안쪽' 스크롤 컨테이너를 맨 아래로 내리고, 현재 li 개수를 돌려준다.
# 네이버 목록 컨테이너의 고정 id(#_pcmap_list_scroll_container)를 우선 쓰고,
# 없으면 overflow 가 scroll 인 엘리먼트 중 li 가 가장 많은 것으로 폴백한다.
# (window 바깥 스크롤은 목록 페이지네이션을 트리거하지 못함 — 반드시 내부 컨테이너)
_SCROLL_INNER_JS = """
() => {
  let el = document.querySelector('#_pcmap_list_scroll_container');
  if (!el) {
    let best = null, bestScore = 0;
    for (const c of document.querySelectorAll('div, ul, section')) {
      const oy = getComputedStyle(c).overflowY;
      if ((oy === 'auto' || oy === 'scroll') &&
          c.scrollHeight > c.clientHeight + 200) {
        const score = c.scrollHeight + c.querySelectorAll('li').length * 1000;
        if (score > bestScore) { bestScore = score; best = c; }
      }
    }
    el = best;
  }
  if (!el) { window.scrollTo(0, document.body.scrollHeight); return -1; }
  el.scrollTop = el.scrollHeight;
  return el.querySelectorAll('li').length;
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
        scrolls = 40 if fetch_all else 15   # plateau 감지로 수렴 시 조기 종료

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
        cx, cy = poly.centroid.x, poly.centroid.y  # 검색을 폴리곤 지역으로 localize
        url = _LIST_URL.format(q=quote(term), x=cx, y=cy)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_timeout(3000)
        except Exception:
            return

        # 내부 컨테이너를 점진 스크롤. li 개수가 더 안 늘면(plateau) 조기 종료.
        last = -1
        stable = 0
        for _ in range(scrolls):
            try:
                count = await page.evaluate(_SCROLL_INNER_JS)
            except Exception:
                count = last
            await page.wait_for_timeout(1100)
            if count <= last:
                stable += 1
                if stable >= 2:  # 2연속 증가 없음 → 끝까지 로드됨
                    break
            else:
                stable = 0
            last = count

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
