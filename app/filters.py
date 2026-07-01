"""평점 / 리뷰수 / 후기미제공 필터."""
from __future__ import annotations

from typing import List

from .models import Place


def passes(place: Place, rule: dict) -> bool:
    """소스별 필터 rule 로 한 장소를 통과시킬지 판정.

    rule 예: {"min_rating": 3.5, "min_reviews": 10, "include_no_score": False}
    """
    min_rating = float(rule.get("min_rating", 0) or 0)
    min_reviews = int(rule.get("min_reviews", 0) or 0)
    include_no_score = bool(rule.get("include_no_score", False))

    has_score = place.rating is not None or place.review_count > 0

    # 평점/후기 정보가 아예 없는 장소 처리
    if not has_score:
        return include_no_score

    # 평점 필터 (min_rating 이 0 이면 미적용)
    if min_rating > 0:
        if place.rating is None:
            # 별점 자체가 없으면(네이버 등) 평점 조건은 통과로 간주하고
            # 리뷰수 조건만 본다. 별점 강제하려면 include_no_score=False + min_rating 로.
            pass
        elif place.rating < min_rating:
            return False

    # 리뷰수 필터
    if min_reviews > 0 and place.review_count < min_reviews:
        return False

    return True


def apply_filters(places: List[Place], filters: dict) -> List[Place]:
    """소스별 rule 을 적용해 통과한 장소만 반환."""
    out: List[Place] = []
    for p in places:
        rule = filters.get(p.source, {})
        if passes(p, rule):
            out.append(p)
    return out
