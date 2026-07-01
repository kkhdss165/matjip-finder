// ── 맛집 검색기 프론트엔드 ─────────────────────────────────────────
let cfg = null;
let drawnGeometry = null;      // 현재 그린 영역의 GeoJSON geometry
const selectedCats = new Set();
let markersLayer = null;

// 1) 지도 초기화 (서울 시청 중심)
const map = L.map("map").setView([37.5665, 126.9780], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap",
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
markersLayer = new L.FeatureGroup().addTo(map);

const drawControl = new L.Control.Draw({
  draw: {
    polygon: { allowIntersection: false, showArea: true },
    rectangle: {},
    polyline: false, circle: false, marker: false, circlemarker: false,
  },
  edit: { featureGroup: drawnItems, remove: true },
});
map.addControl(drawControl);

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();               // 한 번에 하나의 영역만
  drawnItems.addLayer(e.layer);
  drawnGeometry = e.layer.toGeoJSON().geometry;
  setStatus("영역 설정됨. 카테고리를 고르고 검색하세요.");
});
map.on(L.Draw.Event.DELETED, () => { drawnGeometry = null; });
map.on(L.Draw.Event.EDITED, (e) => {
  e.layers.eachLayer((l) => { drawnGeometry = l.toGeoJSON().geometry; });
});

// 2) 설정 로드 → UI 구성
fetch("/api/config").then((r) => r.json()).then((data) => {
  cfg = data;
  if (data.mock) document.getElementById("mock-badge").classList.remove("hidden");
  document.getElementById("limit").value = data.default_limit;
  buildCategories(data.categories);
  buildRatingFilters(data.sources, data.rating_defaults);
});

function buildCategories(categories) {
  const box = document.getElementById("categories");
  categories.forEach((c) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = c.label;
    chip.onclick = () => {
      if (selectedCats.has(c.key)) { selectedCats.delete(c.key); chip.classList.remove("on"); }
      else { selectedCats.add(c.key); chip.classList.add("on"); }
    };
    box.appendChild(chip);
  });
}

function buildRatingFilters(sources, defaults) {
  const box = document.getElementById("rating-filters");
  Object.keys(sources).forEach((src) => {
    if (!sources[src]) return;
    const d = (defaults && defaults[src]) || { min_rating: 0, min_reviews: 0, include_no_score: false };
    const div = document.createElement("div");
    div.className = "src-filter";
    div.dataset.source = src;
    div.innerHTML = `
      <h3>${src === "kakao" ? "카카오" : "네이버"}</h3>
      <div class="row">최소 평점 <input type="number" step="0.1" min="0" max="5" class="f-rating" value="${d.min_rating ?? 0}"></div>
      <div class="row">최소 리뷰수 <input type="number" min="0" class="f-reviews" value="${d.min_reviews ?? 0}"></div>
      <label class="row"><input type="checkbox" class="f-noscore" ${d.include_no_score ? "checked" : ""}> 평점/후기 미제공도 포함</label>
    `;
    box.appendChild(div);
  });
}

function collectFilters() {
  const filters = {};
  document.querySelectorAll(".src-filter").forEach((div) => {
    filters[div.dataset.source] = {
      min_rating: parseFloat(div.querySelector(".f-rating").value) || 0,
      min_reviews: parseInt(div.querySelector(".f-reviews").value) || 0,
      include_no_score: div.querySelector(".f-noscore").checked,
    };
  });
  return filters;
}

// 3) 검색
const btn = document.getElementById("search-btn");
btn.onclick = () => {
  if (!drawnGeometry) { setStatus("먼저 지도에서 영역을 그려주세요.", true); return; }

  const payload = {
    geojson: drawnGeometry,
    categories: [...selectedCats],
    limit_per_source: parseInt(document.getElementById("limit").value) || 30,
    fetch_all: document.getElementById("fetch-all").checked,
    filters: collectFilters(),
  };

  btn.disabled = true;
  setStatus("수집 중… (영역이 넓으면 시간이 걸립니다)");
  fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (!ok) { setStatus(j.error || "오류", true); return; }
      renderResults(j);
    })
    .catch((e) => setStatus("요청 실패: " + e, true))
    .finally(() => { btn.disabled = false; });
};

// 4) 결과 렌더 (병합된 식당 단위 테이블 + 마커)
const SRC_LABEL = { naver: "네이버", kakao: "카카오" };

function renderResults(data) {
  const parts = Object.entries(data.per_source || {}).map(([k, v]) => `${SRC_LABEL[k] || k} ${v}`);
  setStatus(`완료 · 타일 ${data.tiles}개 · 병합 전 [${parts.join(" / ")}] · 식당 ${data.count}곳`);

  document.getElementById("results-pane").classList.remove("hidden");
  document.getElementById("result-count").textContent = `(${data.count}곳)`;

  const sources = data.sources || [];
  const thead = document.querySelector("#results-table thead");
  thead.innerHTML = `<tr><th>#</th><th>이름</th><th>카테고리</th>` +
    sources.map((s) => `<th>${SRC_LABEL[s] || s}</th>`).join("") +
    `<th>지도</th></tr>`;

  const tbody = document.querySelector("#results-table tbody");
  tbody.innerHTML = "";
  markersLayer.clearLayers();

  data.places.forEach((p, i) => {
    const srcCells = sources.map((s) => `<td>${srcCell(p.sources[s], s)}</td>`).join("");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td class="name">${esc(p.name)}</td>
      <td>${esc(p.category)}</td>
      ${srcCells}
      <td><a href="#" data-i="${i}" class="goto">보기</a></td>`;
    tbody.appendChild(tr);

    const popup = `<b>${esc(p.name)}</b><br>` +
      sources.map((s) => `${SRC_LABEL[s] || s}: ${srcText(p.sources[s])}`).join("<br>");
    const marker = L.marker([p.lat, p.lng]).bindPopup(popup);
    p._marker = marker;
    markersLayer.addLayer(marker);
  });

  // "보기" 클릭 → 지도에서 해당 마커로 이동
  tbody.querySelectorAll("a.goto").forEach((a) => {
    a.onclick = (e) => {
      e.preventDefault();
      const p = data.places[parseInt(a.dataset.i)];
      map.setView([p.lat, p.lng], 17);
      p._marker.openPopup();
    };
  });

  if (data.places.length) map.fitBounds(markersLayer.getBounds().pad(0.1));
}

// 소스 셀: "4.4 (리뷰 7)" 또는 "미제공"
function srcCell(s, src) {
  if (!s) return `<span class="na">${SRC_LABEL[src] || src} 미제공</span>`;
  const rating = s.rating != null ? `<b>${s.rating}</b>` : "평점없음";
  const link = s.url ? ` <a href="${s.url}" target="_blank">↗</a>` : "";
  return `${rating} <span class="rev">(리뷰 ${fmt(s.review_count)})</span>${link}`;
}
function srcText(s) {
  if (!s) return "미제공";
  return `${s.rating != null ? s.rating : "평점없음"} (리뷰 ${fmt(s.review_count)})`;
}
function fmt(n) {
  n = n || 0;
  return n >= 10000 ? (n / 10000).toFixed(1) + "만" : n.toLocaleString();
}

function setStatus(msg, isError) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status" + (isError ? " error" : "");
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
