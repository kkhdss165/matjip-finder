"""검색 결과로 다루는 공통 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Place:
    """카카오/네이버 어느 소스든 이 형태로 정규화해서 다룬다."""

    source: str                      # "kakao" | "naver"
    place_id: str                    # 소스 내부 고유 id (중복 제거용)
    name: str
    lat: float
    lng: float
    category: str = ""               # 소스가 준 카테고리 문자열
    matched_category: str = ""       # 우리가 검색에 쓴 카테고리 key
    address: str = ""
    road_address: str = ""
    phone: str = ""
    url: str = ""                    # 상세 페이지 링크

    rating: Optional[float] = None   # 별점 (없으면 None)
    review_count: int = 0            # 리뷰/후기 총합 (방문자+블로그 등)

    def key(self) -> str:
        """소스 간/내 중복 제거 키."""
        return f"{self.source}:{self.place_id}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchRequest:
    """UI에서 넘어온 한 번의 검색 요청."""

    geojson: dict                                  # 그린 다각형/사각형 (GeoJSON geometry)
    categories: list                               # 선택된 카테고리 key 목록
    limit_per_source: int = 30                     # 소스별 수집 개수
    fetch_all: bool = False                        # "모두 가져오기" 체크 여부
    # 소스별 필터: {"kakao": {min_rating, min_reviews, include_no_score}, "naver": {...}}
    filters: dict = field(default_factory=dict)
