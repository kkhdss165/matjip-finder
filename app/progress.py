"""수집 진행상태 공유 (단일 사용자 로컬 도구라 전역 하나로 충분).

runner/scraper 가 갱신하고, /api/progress 가 스냅샷을 읽어 프론트가 폴링한다.
동시 검색은 영속 프로필 락 때문에 어차피 1건씩만 돌아가므로 전역이면 된다.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_state = {
    "active": False,   # 수집 진행 중 여부
    "phase": "",       # 현재 단계 텍스트 (예: "카카오 평점 보강")
    "done": 0,         # 현재 단계 진행 수
    "total": 0,        # 현재 단계 전체 수 (0 이면 미정)
    "count": 0,        # 지금까지 확보한 결과 수(참고)
}


def start() -> None:
    with _lock:
        _state.update({"active": True, "phase": "검색 시작", "done": 0, "total": 0, "count": 0})


def update(phase: str = None, done: int = None, total: int = None, count: int = None) -> None:
    with _lock:
        if phase is not None:
            _state["phase"] = phase
        if done is not None:
            _state["done"] = done
        if total is not None:
            _state["total"] = total
        if count is not None:
            _state["count"] = count


def finish() -> None:
    with _lock:
        _state["active"] = False
        _state["phase"] = "완료"


def snapshot() -> dict:
    with _lock:
        return dict(_state)
