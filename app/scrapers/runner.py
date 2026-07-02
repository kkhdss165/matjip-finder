"""검색 한 건을 실제로 수행하는 오케스트레이터.

파이프라인:
    GeoJSON → 격자 타일 → (소스별) collect() 수집 → 다각형 내부 필터
            → 평점/리뷰 필터(소스별, 병합 전) → 소스 간 식당 병합
            → 정렬 → 개수 제한(trim)
"""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List

from playwright.async_api import async_playwright

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROFILE_DIR = os.path.join(_ROOT, ".browser_profile")

# 자동화 탐지 회피 (navigator.webdriver 등 숨김). 모든 페이지에 주입.
_STEALTH = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'languages',{get:()=>['ko-KR','ko']});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});"
    "window.chrome={runtime:{}};"
)

from .. import filters as filt
from ..geo import make_grid, to_polygon
from ..merge import merge_places
from ..models import Place, SearchRequest
from .kakao import KakaoScraper
from .mock import MockScraper
from .naver import NaverScraper


def _build_scrapers(settings: dict) -> Dict[str, object]:
    sources = settings.get("sources", {})
    mock = bool(settings.get("scrape", {}).get("mock", False))
    scrapers: Dict[str, object] = {}
    if sources.get("kakao"):
        scrapers["kakao"] = MockScraper(settings, "kakao") if mock else KakaoScraper(settings)
    if sources.get("naver"):
        scrapers["naver"] = MockScraper(settings, "naver") if mock else NaverScraper(settings)
    return scrapers


def _terms_for(categories: List[str], filters_cfg: dict) -> List[str]:
    """선택된 카테고리 key → 실제 검색어 목록. 없으면 '맛집' 하나."""
    by_key = {c["key"]: c for c in filters_cfg.get("categories", [])}
    terms: List[str] = []
    for key in categories:
        c = by_key.get(key)
        if c:
            terms.extend(c.get("terms", []) or [c["label"]])
    if not terms:
        terms = ["맛집"]
    seen, uniq = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


async def _search_async(request: SearchRequest, settings: dict, filters_cfg: dict) -> dict:
    poly = to_polygon(request.geojson)
    grid_cfg = settings.get("grid", {})
    tiles = make_grid(poly,
                      tile_size_m=float(grid_cfg.get("tile_size_m", 700)),
                      max_tiles=int(grid_cfg.get("max_tiles", 60)))

    terms = _terms_for(request.categories, filters_cfg)
    scrapers = _build_scrapers(settings)
    all_sources = list(scrapers.keys())

    scfg = settings.get("scrape", {})
    coll = settings.get("collection", {})
    hard_cap = int(coll.get("hard_cap", 300))
    limit = hard_cap if request.fetch_all else min(int(request.limit_per_source), hard_cap)

    survivors: List[Place] = []
    per_source: Dict[str, int] = {}

    mock = bool(scfg.get("mock", False))
    headless = bool(scfg.get("headless", True))
    ua = scfg.get("user_agent") or None
    # 네이버는 '구' 헤드리스(--headless)면 봇 차단(405). 대신 크롬 'new headless'
    # (--headless=new)를 쓰면 창 없이도 실제 브라우저처럼 렌더돼 통과한다.
    # 그래서 playwright headless 는 항상 False 로 두고, 창을 숨기려면 --headless=new 를 넣는다.
    args = ["--disable-blink-features=AutomationControlled"]
    if headless:
        args.append("--headless=new")   # 창 없이 실행(권장). headless:false 면 창이 보임(디버그용).

    async with async_playwright() as pw:
        # 실제 수집은 영속 프로필(쿠키/세션 유지 → 봇 탐지 완화)로,
        # mock 은 일회용 컨텍스트로.
        if mock:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=ua, locale="ko-KR")
            closer = browser
        else:
            # headless 는 args 의 --headless=new 로 제어하므로 여기선 항상 False.
            context = await pw.chromium.launch_persistent_context(
                _PROFILE_DIR, headless=False, args=args,
                user_agent=ua, locale="ko-KR",
                viewport={"width": 1280, "height": 900})
            closer = context
        try:
            await context.add_init_script(_STEALTH)
            print(f"[검색] 타일 {len(tiles)}개 · 검색어 {terms} · 소스 {all_sources}",
                  flush=True)
            for name, scraper in scrapers.items():
                print(f"[{name}] 수집 시작", flush=True)
                kept = await scraper.collect(
                    context, tiles, terms, poly, limit,
                    request.fetch_all, hard_cap)
                # 선택한 카테고리에 실제로 해당하는 것만 남김(엉뚱한 카테고리 혼입 제거)
                before = len(kept)
                kept = filt.filter_by_category(
                    kept, request.categories, filters_cfg.get("categories", []))
                # 소스별 평점/리뷰 필터를 병합 전에 적용(각 소스 기준 통과분만 남김)
                kept = filt.apply_filters(kept, request.filters)
                print(f"[{name}] 카테고리+평점 필터 {before} → {len(kept)}곳", flush=True)
                per_source[name] = len(kept)
                survivors.extend(kept)
        finally:
            await closer.close()

    merged = merge_places(survivors, all_sources)
    if not request.fetch_all:
        merged = merged[:limit]
    print(f"[검색 완료] 병합 {len(merged)}곳 (표시 상한 {limit})", flush=True)

    return {
        "count": len(merged),
        "tiles": len(tiles),
        "per_source": per_source,   # 병합 전 소스별 통과 개수
        "sources": all_sources,
        "places": merged,
    }


def run_search(request: SearchRequest, settings: dict, filters_cfg: dict) -> dict:
    """동기 진입점 (Flask 라우트에서 호출)."""
    return asyncio.run(_search_async(request, settings, filters_cfg))
