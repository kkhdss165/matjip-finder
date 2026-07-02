"""YAML 설정 파일 로더.

settings.yaml(커밋됨) 위에 settings.local.yaml(gitignore, 비밀 키용)을
있으면 깊은 병합(deep-merge)으로 덮어쓴다. 실제 API 키는 local 파일에만 둔다.
"""
from __future__ import annotations

import os
import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_ROOT, "config")


def _load(name: str) -> dict:
    path = os.path.join(_CONFIG_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """override 값으로 base 를 재귀 병합(제자리 수정 후 반환)."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_settings() -> dict:
    settings = _load("settings.yaml")
    local = _load("settings.local.yaml")   # 있으면 비밀 값 덮어쓰기
    if local:
        _deep_merge(settings, local)
    return settings


def load_filters() -> dict:
    return _load("filters.yaml")
