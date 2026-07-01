"""Flask 서버 — 지도 UI 제공 + 검색 API."""
from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, render_template, request

from .config import load_filters, load_settings
from .models import SearchRequest
from .scrapers.runner import run_search

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(_ROOT, "templates"),
    static_folder=os.path.join(_ROOT, "static"),
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    """UI 초기화용 설정: 카테고리 목록, 필터 기본값, 기본 개수, 활성 소스."""
    settings = load_settings()
    filters = load_filters()
    return jsonify({
        "categories": filters.get("categories", []),
        "rating_defaults": filters.get("rating", {}),
        "default_limit": settings.get("collection", {}).get("default_limit", 30),
        "hard_cap": settings.get("collection", {}).get("hard_cap", 300),
        "sources": settings.get("sources", {}),
        "mock": settings.get("scrape", {}).get("mock", False),
    })


@app.route("/api/search", methods=["POST"])
def api_search():
    settings = load_settings()
    filters_cfg = load_filters()
    body = request.get_json(force=True, silent=True) or {}

    geojson = body.get("geojson")
    if not geojson:
        return jsonify({"error": "지도에서 영역을 먼저 그려주세요."}), 400

    req = SearchRequest(
        geojson=geojson,
        categories=body.get("categories", []),
        limit_per_source=int(body.get("limit_per_source", 30)),
        fetch_all=bool(body.get("fetch_all", False)),
        filters=body.get("filters", {}),
    )
    try:
        result = run_search(req, settings, filters_cfg)
        return jsonify(result)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"검색 중 오류: {e}"}), 500


def main():
    settings = load_settings()
    srv = settings.get("server", {})
    app.run(
        host=srv.get("host", "127.0.0.1"),
        port=int(srv.get("port", 5000)),
        debug=bool(srv.get("debug", True)),
    )


if __name__ == "__main__":
    main()
