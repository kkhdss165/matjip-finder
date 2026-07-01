"""소스 간 같은 식당 병합.

카카오 결과와 네이버 결과를 '이름 정규화 + 위치 근접'으로 매칭해
식당 하나당 한 행으로 합친다. 결과 예:

    팔당족발
      네이버 4.66 (리뷰 11000)
      카카오 미제공
"""
from __future__ import annotations

import re
from typing import Dict, List

from .geo import haversine_m
from .models import Place

_MATCH_DIST_M = 80.0   # 같은 이름이 이 거리 안이면 동일 식당으로 간주
_SPACE = re.compile(r"\s+")
_PAREN = re.compile(r"\(.*?\)")


def _norm(name: str) -> str:
    name = _PAREN.sub("", name or "")
    name = _SPACE.sub("", name).lower()
    return name


class Merged:
    def __init__(self, place: Place):
        self.name = place.name
        self.norm = _norm(place.name)
        self.category = place.category
        self.lat = place.lat
        self.lng = place.lng
        self.sources: Dict[str, dict] = {}
        self.add(place)

    def add(self, p: Place) -> None:
        self.sources[p.source] = {
            "rating": p.rating,
            "review_count": p.review_count,
            "url": p.url,
            "category": p.category,
        }
        # 대표 이름/카테고리는 더 긴 쪽(정보 많은 쪽)으로
        if len(p.name) > len(self.name):
            self.name = p.name
        if not self.category and p.category:
            self.category = p.category

    def matches(self, p: Place) -> bool:
        return (self.norm == _norm(p.name)
                and haversine_m(self.lat, self.lng, p.lat, p.lng) <= _MATCH_DIST_M)

    @property
    def best_rating(self) -> float:
        vals = [s["rating"] for s in self.sources.values() if s.get("rating")]
        return max(vals) if vals else 0.0

    @property
    def total_reviews(self) -> int:
        return sum(s.get("review_count", 0) for s in self.sources.values())

    def to_dict(self, all_sources: List[str]) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "lat": self.lat,
            "lng": self.lng,
            # 모든 소스 키를 채우되, 없는 소스는 None → UI 에서 "미제공" 표시
            "sources": {s: self.sources.get(s) for s in all_sources},
            "best_rating": self.best_rating,
            "total_reviews": self.total_reviews,
        }


def merge_places(places: List[Place], all_sources: List[str]) -> List[dict]:
    groups: List[Merged] = []
    # 이름 정규화 기준 버킷으로 후보를 좁혀서 매칭 비용을 줄인다
    by_norm: Dict[str, List[Merged]] = {}
    for p in places:
        key = _norm(p.name)
        hit = None
        for g in by_norm.get(key, []):
            if g.matches(p):
                hit = g
                break
        if hit:
            hit.add(p)
        else:
            g = Merged(p)
            groups.append(g)
            by_norm.setdefault(key, []).append(g)

    result = [g.to_dict(all_sources) for g in groups]
    result.sort(key=lambda d: (d["best_rating"], d["total_reviews"]), reverse=True)
    return result
