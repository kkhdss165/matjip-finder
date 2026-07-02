// ── 맛집 검색기 (네이버맵 스타일 UI) ─────────────────────────────
let cfg = null;
let drawnGeometry = null;
const selectedCats = new Set();
let markersLayer = null;
let cards = [];       // {el, marker, pinEl, place}
let activeIdx = -1;
const SRC_LABEL = { naver: "네이버", kakao: "카카오" };

// 1) 지도
const map = L.map("map", { zoomControl: true }).setView([37.5665, 126.9780], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap",
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
markersLayer = new L.FeatureGroup().addTo(map);

map.addControl(new L.Control.Draw({
  draw: { polygon: { allowIntersection: false, showArea: true }, rectangle: {},
          polyline: false, circle: false, marker: false, circlemarker: false },
  edit: { featureGroup: drawnItems, remove: true },
}));

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  drawnGeometry = e.layer.toGeoJSON().geometry;
  hideHint();
  setStatus("영역 설정됨. 카테고리를 고르고 검색하세요.");
});
map.on(L.Draw.Event.DELETED, () => { drawnGeometry = null; });
map.on(L.Draw.Event.EDITED, (e) => e.layers.eachLayer((l) => { drawnGeometry = l.toGeoJSON().geometry; }));

function hideHint() { const h = document.getElementById("map-hint"); if (h) h.style.display = "none"; }

// 2) 설정 로드
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
  const color = { naver: "var(--naver)", kakao: "var(--kakao)" };
  Object.keys(sources).forEach((src) => {
    if (!sources[src]) return;
    const d = (defaults && defaults[src]) || { min_rating: 0, min_reviews: 0, include_no_score: false };
    const div = document.createElement("div");
    div.className = "src-filter";
    div.dataset.source = src;
    div.innerHTML = `
      <h3><span class="dot" style="background:${color[src]}"></span>${SRC_LABEL[src] || src}</h3>
      <div class="row">최소 평점 <input type="number" step="0.1" min="0" max="5" class="f-rating" value="${d.min_rating ?? 0}"></div>
      <div class="row">최소 리뷰 <input type="number" min="0" class="f-reviews" value="${d.min_reviews ?? 0}"></div>
      <label class="row"><input type="checkbox" class="f-noscore" ${d.include_no_score ? "checked" : ""}> 평점/후기 미제공도 포함</label>`;
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
let pollTimer = null;
let searchStart = 0;

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
  searchStart = Date.now();
  setStatus("⏳ 수집 준비 중…");
  startPolling();
  fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(payload) })
    .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (ok) { j._elapsed = (Date.now() - searchStart) / 1000; renderResults(j); collapseSearch(); }
      else setStatus(j.error || "오류", true);
    })
    .catch((e) => setStatus("요청 실패: " + e, true))
    .finally(() => { stopPolling(); btn.disabled = false; });
};

// ① 진행률 폴링
function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const p = await fetch("/api/progress").then((r) => r.json());
      if (!p.active) return;
      let txt = p.phase || "수집 중";
      if (p.total > 0) {
        const pct = Math.round((p.done / p.total) * 100);
        txt += ` ${p.done}/${p.total} (${pct}%)`;
      }
      const sec = ((Date.now() - searchStart) / 1000).toFixed(0);
      setStatus(`⏳ ${txt} · ${sec}초`);
    } catch (e) { /* ignore */ }
  }, 1000);
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

// 검색 패널 접기/펼치기 (결과 공간 확보)
function collapseSearch() {
  document.getElementById("ss-detail").textContent = buildSummaryText();
  document.getElementById("search-panel").classList.add("hidden");
  document.getElementById("search-summary").classList.remove("hidden");
}
function expandSearch() {
  document.getElementById("search-panel").classList.remove("hidden");
  document.getElementById("search-summary").classList.add("hidden");
}
document.getElementById("search-summary").onclick = expandSearch;

function buildSummaryText() {
  const labels = (cfg.categories || []).filter((c) => selectedCats.has(c.key)).map((c) => c.label);
  const cat = labels.length ? labels.join("·") : "전체";
  const f = collectFilters();
  const parts = [cat];
  Object.keys(f).forEach((src) => {
    const bits = [];
    if (f[src].min_rating > 0) bits.push(`★${f[src].min_rating}↑`);
    if (f[src].min_reviews > 0) bits.push(`리뷰${f[src].min_reviews}↑`);
    if (bits.length) parts.push(`${SRC_LABEL[src] || src} ${bits.join(" ")}`);
  });
  const allChk = document.getElementById("fetch-all").checked;
  parts.push(allChk ? "모두" : `${document.getElementById("limit").value}개`);
  return parts.join(" · ");
}

// 4) 결과 상태 저장 + 뷰(필터/정렬) 렌더
let allPlaces = [];       // 검색 원본 (필터/정렬은 이 위에서만, 재검색 없음)
let resultSources = [];
const catFilter = new Set();  // 결과 내 카테고리 필터 (비어있으면 전체)

function renderResults(data) {
  allPlaces = data.places || [];
  resultSources = data.sources || [];

  const parts = Object.entries(data.per_source || {}).map(([k, v]) => `${SRC_LABEL[k] || k} ${v}`);
  const sec = data._elapsed != null ? ` · ${data._elapsed.toFixed(1)}초` : "";
  setStatus(`완료 · 타일 ${data.tiles}개 · [${parts.join(" / ")}]${sec}`);

  document.getElementById("result-section").classList.remove("hidden");
  document.getElementById("result-sub").textContent = sec;

  // 결과 내 카테고리 필터 칩 (검색에 쓴 카테고리들)
  catFilter.clear();
  buildCatFilterChips();
  document.getElementById("name-filter").value = "";
  document.getElementById("sort-select").value = "default";

  applyView();
}

function buildCatFilterChips() {
  const box = document.getElementById("cat-filter");
  box.innerHTML = "";
  const keys = (cfg.categories || []).filter((c) => selectedCats.has(c.key));
  if (keys.length < 2) return;  // 카테고리 1개 이하면 필터 칩 불필요
  keys.forEach((c) => {
    const chip = document.createElement("span");
    chip.className = "chip mini-chip";
    chip.textContent = c.label;
    chip.onclick = () => {
      if (catFilter.has(c.key)) { catFilter.delete(c.key); chip.classList.remove("on"); }
      else { catFilter.add(c.key); chip.classList.add("on"); }
      applyView();
    };
    box.appendChild(chip);
  });
}

// 필터 + 정렬 적용 후 카드/핀 렌더
function applyView() {
  let view = allPlaces.slice();

  // 가게명 검색
  const q = document.getElementById("name-filter").value.trim().toLowerCase();
  if (q) view = view.filter((p) => (p.name || "").toLowerCase().includes(q));

  // 카테고리 필터 (선택된 게 있으면 그 카테고리들만)
  if (catFilter.size) {
    const byKey = {};
    (cfg.categories || []).forEach((c) => (byKey[c.key] = c));
    view = view.filter((p) => {
      const cat = p.category || "";
      return [...catFilter].some((k) => (byKey[k].match || [byKey[k].label]).some((m) => cat.includes(m)));
    });
  }

  sortView(view, document.getElementById("sort-select").value);
  renderCards(view);
  document.getElementById("result-count").textContent = view.length;
}

function ratingOf(p, src) { const s = p.sources[src]; return s && s.rating != null ? s.rating : null; }
function reviewsOf(p) { return resultSources.reduce((a, s) => a + ((p.sources[s] && p.sources[s].review_count) || 0), 0); }

function sortView(view, mode) {
  const byRating = (src, dir) => (a, b) => {
    const ra = ratingOf(a, src), rb = ratingOf(b, src);
    if (ra == null && rb == null) return 0;
    if (ra == null) return 1;   // 평점 없는 곳은 항상 뒤로
    if (rb == null) return -1;
    return dir * (rb - ra);
  };
  switch (mode) {
    case "name-asc": view.sort((a, b) => a.name.localeCompare(b.name, "ko")); break;
    case "name-desc": view.sort((a, b) => b.name.localeCompare(a.name, "ko")); break;
    case "kakao-desc": view.sort(byRating("kakao", 1)); break;
    case "kakao-asc": view.sort(byRating("kakao", -1)); break;
    case "naver-desc": view.sort(byRating("naver", 1)); break;
    case "naver-asc": view.sort(byRating("naver", -1)); break;
    case "review-desc": view.sort((a, b) => reviewsOf(b) - reviewsOf(a)); break;
    default: break;  // 서버가 준 기본 순서(평점·리뷰) 유지
  }
}

function renderCards(places) {
  const list = document.getElementById("result-list");
  list.innerHTML = "";
  markersLayer.clearLayers();
  cards = [];
  activeIdx = -1;

  if (!places.length) {
    list.innerHTML = '<div style="padding:24px;color:var(--sub);font-size:13px;text-align:center">조건에 맞는 결과가 없습니다.</div>';
    return;
  }

  places.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "place-card";
    card.innerHTML = `
      <div class="rank">${i + 1}</div>
      <div class="pc-body">
        <div class="pc-name">${esc(p.name)}</div>
        <div class="pc-cat">${esc(p.category) || "-"}</div>
        <div class="pc-sources">${resultSources.map((s) => srcRow(p.sources[s], s)).join("")}</div>
      </div>`;
    card.onclick = () => focusPlace(i);
    list.appendChild(card);

    const top = i < 3;
    const pin = L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 26],
      html: `<div class="map-pin ${top ? "top" : ""}"><span>${i + 1}</span></div>` });
    const marker = L.marker([p.lat, p.lng], { icon: pin }).addTo(markersLayer);
    marker.bindPopup(popupHtml(p, resultSources));
    marker.on("click", () => focusPlace(i, false));

    cards.push({ el: card, marker, place: p });
  });

  map.fitBounds(markersLayer.getBounds().pad(0.15));
  list.scrollTop = 0;
}

// 필터/정렬 입력 이벤트
document.getElementById("name-filter").addEventListener("input", applyView);
document.getElementById("sort-select").addEventListener("change", applyView);

function focusPlace(i, pan = true) {
  if (activeIdx >= 0 && cards[activeIdx]) cards[activeIdx].el.classList.remove("active");
  activeIdx = i;
  const c = cards[i];
  c.el.classList.add("active");
  c.el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  if (pan) map.setView([c.place.lat, c.place.lng], Math.max(map.getZoom(), 16), { animate: true });
  c.marker.openPopup();
}

function srcRow(s, src) {
  const who = `<span class="who ${src}">${SRC_LABEL[src] || src}</span>`;
  if (!s) return `<div class="pc-src na">${who}<span>미제공</span></div>`;
  const score = s.rating != null
    ? `<span class="score"><span class="star">★</span>${s.rating}</span>`
    : `<span class="score" style="color:var(--sub)">평점없음</span>`;
  // 카드 클릭(지도 이동)과 겹치지 않게 링크 클릭은 전파 중단
  const link = s.url
    ? `<a class="pc-src-link ${src}" href="${s.url}" target="_blank" onclick="event.stopPropagation()">바로가기 ↗</a>`
    : "";
  return `<div class="pc-src">${who}${score}<span class="rev">리뷰 ${fmt(s.review_count)}</span>${link}</div>`;
}

function popupHtml(p, sources) {
  const rows = (sources || []).map((s) => {
    const d = p.sources[s];
    const label = SRC_LABEL[s] || s;
    if (!d) return `${label}: 미제공`;
    const link = d.url ? ` <a href="${d.url}" target="_blank">↗</a>` : "";
    return `${label}: ${d.rating != null ? "★" + d.rating : "평점없음"} · 리뷰 ${fmt(d.review_count)}${link}`;
  }).join("<br>");
  return `<b>${esc(p.name)}</b><br><span style="color:#888">${esc(p.category)}</span><br>${rows}`;
}

function setStatus(msg, isError) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status" + (isError ? " error" : "");
}
function fmt(n) { n = n || 0; return n >= 10000 ? (n / 10000).toFixed(1) + "만" : n.toLocaleString(); }
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
