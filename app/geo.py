"""GeoJSON 다각형을 다루는 지리 연산.

흐름:
    GeoJSON Polygon  ->  bbox  ->  격자(grid) 타일들  ->  소스에 rect/center 로 검색
    검색 결과 좌표  ->  원래 Polygon 내부인지 point-in-polygon 판정
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from shapely.geometry import shape, Point, Polygon

_M_PER_DEG_LAT = 111_320.0  # 위도 1도당 대략 미터


@dataclass
class Tile:
    """격자 한 칸. 소스 검색에 넘길 사각형 + 중심 + 반경."""
    min_lng: float
    min_lat: float
    max_lng: float
    max_lat: float

    @property
    def center(self) -> tuple:
        return ((self.min_lng + self.max_lng) / 2.0,
                (self.min_lat + self.max_lat) / 2.0)

    @property
    def radius_m(self) -> float:
        """중심에서 모서리까지 거리(미터) — 반경 검색용."""
        clng, clat = self.center
        dlat_m = (self.max_lat - clat) * _M_PER_DEG_LAT
        dlng_m = (self.max_lng - clng) * _M_PER_DEG_LAT * math.cos(math.radians(clat))
        return math.hypot(dlat_m, dlng_m)


def to_polygon(geojson_geometry: dict) -> Polygon:
    """GeoJSON geometry(dict) -> shapely Polygon.

    Leaflet.draw 는 사각형도 Polygon geometry 로 내보내므로 그대로 처리된다.
    """
    geom = shape(geojson_geometry)
    if geom.geom_type != "Polygon":
        # MultiPolygon 등은 convex hull 로 단순화
        geom = geom.convex_hull
    return geom


def bbox_of(poly: Polygon) -> tuple:
    """(min_lng, min_lat, max_lng, max_lat)"""
    return poly.bounds


def make_grid(poly: Polygon, tile_size_m: float, max_tiles: int) -> List[Tile]:
    """다각형 bbox 를 tile_size_m 크기 격자로 분할.

    - 다각형과 겹치지 않는 타일은 버린다(요청 낭비 방지).
    - 타일 수가 max_tiles 를 넘으면 타일 크기를 자동으로 키워 상한을 지킨다.
    """
    min_lng, min_lat, max_lng, max_lat = poly.bounds
    mid_lat = (min_lat + max_lat) / 2.0

    while True:
        dlat = tile_size_m / _M_PER_DEG_LAT
        dlng = tile_size_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 1e-6))

        n_lat = max(1, math.ceil((max_lat - min_lat) / dlat))
        n_lng = max(1, math.ceil((max_lng - min_lng) / dlng))

        if n_lat * n_lng <= max_tiles or tile_size_m > 50_000:
            break
        tile_size_m *= 1.5  # 너무 잘게 쪼개지면 타일 크기를 키워 재시도

    tiles: List[Tile] = []
    for i in range(n_lat):
        for j in range(n_lng):
            t = Tile(
                min_lng=min_lng + j * dlng,
                min_lat=min_lat + i * dlat,
                max_lng=min(min_lng + (j + 1) * dlng, max_lng),
                max_lat=min(min_lat + (i + 1) * dlat, max_lat),
            )
            tile_poly = Polygon([
                (t.min_lng, t.min_lat), (t.max_lng, t.min_lat),
                (t.max_lng, t.max_lat), (t.min_lng, t.max_lat),
            ])
            if poly.intersects(tile_poly):
                tiles.append(t)
    return tiles


def point_in_polygon(poly: Polygon, lng: float, lat: float) -> bool:
    """좌표가 다각형 내부(경계 포함)인지."""
    p = Point(lng, lat)
    return poly.covers(p)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이 거리(미터). 소스 간 같은 식당 매칭용."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
