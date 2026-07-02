"""오프라인 데모용 가짜 스크래퍼.

네트워크/키 없이 UI·격자·필터·병합·지도 마커 전체 흐름을 검증하려고 쓴다.
config/settings.yaml 의 scrape.mock: true 로 켠다.

카카오/네이버가 '같은 이름·같은 좌표'의 식당을 내도록 해서 병합이 실제로
일어나게 만든다(평점/리뷰는 소스마다 다르게).
"""
from __future__ import annotations

from typing import List

from .base import BaseScraper
from ..geo import Tile
from ..models import Place


class MockScraper(BaseScraper):
    def __init__(self, settings: dict, source: str):
        super().__init__(settings)
        self.source = source

    async def search_tile(self, context, tile: Tile, term: str) -> List[Place]:
        clng, clat = tile.center
        out: List[Place] = []
        # 이름/좌표는 소스와 무관(=병합됨), 평점/리뷰만 소스마다 다르게
        base = abs(hash((round(clng, 4), round(clat, 4), term)))
        n = 2 + base % 3
        for i in range(n):
            off_lng = ((base >> (i * 3)) % 7 - 3) * 0.0006
            off_lat = ((base >> (i * 3 + 1)) % 7 - 3) * 0.0006
            src_seed = abs(hash((base, i, self.source)))
            rating = 3.0 + (src_seed % 20) / 10.0   # 3.0 ~ 4.9
            reviews = src_seed % 500
            name = f"{term} 맛집{i + 1}"
            out.append(Place(
                source=self.source,
                place_id=f"{self.source}-{base}-{i}",
                name=name,
                lat=clat + off_lat,
                lng=clng + off_lng,
                category=term,
                matched_category=term,
                address="데모 주소",
                url=f"https://example.com/{self.source}/{base}-{i}",
                rating=round(rating, 1),
                review_count=reviews,
            ))
        return out
