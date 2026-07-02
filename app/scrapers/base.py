"""스크래퍼 공통 베이스."""
from __future__ import annotations

import asyncio
import random
from typing import Dict, List

from ..geo import Tile, point_in_polygon
from ..models import Place


class BaseScraper:
    """각 소스 스크래퍼가 상속.

    - 기본 collect(): 타일×검색어를 search_tile 로 훑는 방식(카카오 dapi 용).
    - 네이버처럼 브라우저 인터셉트가 필요한 소스는 collect() 를 통째로 오버라이드한다.
    """

    source = "base"

    def __init__(self, settings: dict):
        self.settings = settings
        self.scrape_cfg = settings.get("scrape", {})
        self._requests_since_cooldown = 0

    async def collect(self, context, tiles: List[Tile], terms: List[str], poly,
                      limit: int, fetch_all: bool, hard_cap: int) -> List[Place]:
        """타일×검색어를 search_tile 로 수집 → 다각형 내부 필터 → 평점 보강.

        context 는 runner 가 만든 (영속) BrowserContext 를 공유받는다.
        """
        found: Dict[str, Place] = {}
        n = len(tiles)
        for i, tile in enumerate(tiles, 1):
            for term in terms:
                for p in await self.search_tile(context, tile, term):
                    if point_in_polygon(poly, p.lng, p.lat):
                        found.setdefault(p.key(), p)
                await self.search_wait()
            if i % 5 == 0 or i == n:
                print(f"[{self.source}] 타일 {i}/{n} · 누적 {len(found)}곳", flush=True)
        kept = list(found.values())
        enrich_cap = hard_cap if fetch_all else min(hard_cap, max(limit * 4, 40))
        n_enrich = min(len(kept), enrich_cap)
        print(f"[{self.source}] 목록 {len(kept)}곳 → 평점 보강 {n_enrich}곳", flush=True)
        await self.enrich(context, kept[:enrich_cap])
        return kept

    async def search_tile(self, context, tile: Tile, term: str) -> List[Place]:
        """한 격자 타일 × 한 검색어에 대해 장소 목록 반환. 하위 클래스가 구현."""
        raise NotImplementedError

    async def enrich(self, context, places: List[Place]) -> None:
        """목록에 없던 평점/리뷰 등을 상세에서 보강(제자리 수정). 기본은 no-op."""
        return

    # ── 공통 유틸 ────────────────────────────────────────────────
    async def search_wait(self) -> None:
        """목록 검색 루프의 요청 간 대기. 기본은 스크래핑용 polite_wait.
        공식 API(카카오 dapi 등) 소스는 오버라이드해 짧게 둘 수 있다."""
        await self.polite_wait()

    async def polite_wait(self) -> None:
        """요청 사이 랜덤 대기 + 주기적 cooldown (IP 블락 회피)."""
        cfg = self.scrape_cfg
        lo = int(cfg.get("min_delay_ms", 400))
        hi = int(cfg.get("max_delay_ms", 1200))
        await asyncio.sleep(random.randint(lo, max(lo, hi)) / 1000.0)

        self._requests_since_cooldown += 1
        after = int(cfg.get("cooldown_after", 0) or 0)
        if after and self._requests_since_cooldown >= after:
            self._requests_since_cooldown = 0
            await asyncio.sleep(int(cfg.get("cooldown_ms", 5000)) / 1000.0)

    @staticmethod
    def _to_float(v):
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(v) -> int:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0
