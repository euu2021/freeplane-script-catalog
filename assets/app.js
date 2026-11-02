"use strict";

const $ = (id) => document.getElementById(id);
const state = { q: "", kind: "", source: "", sort: "relevance", tags: [] };
let catalog = { entries: [], tags: {} };

const KIND_LABEL = { script: "script", "add-on": "add-on", library: "library", collection: "collection" };
const SOURCE_LABEL = {
  docs: "documentation", "github-repo": "repository",
  "github-discussion": "forum post", "github-issue": "issue comment",
};
const NEW_DAYS = 45;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fold(s) {
  return String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function highlight(text, words) {
  if (!words.length) return esc(text);
  const rx = new RegExp("(" + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  // Split the raw text, then escape each piece: marking escaped HTML would break entities.
  return String(text ?? "").split(rx).map((part, i) => (i % 2 ? `<mark>${esc(part)}</mark>` : esc(part))).join("");
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  state.q = p.get("q") || "";
  state.kind = p.get("kind") || "";
  state.source = p.get("source") || "";
  state.sort = p.get("sort") || "relevance";
  state.tags = (p.get("tags") || "").split(",").filter(Boolean);
}

function writeHash() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.kind) p.set("kind", state.kind);
  if (state.source) p.set("source", state.source);
  if (state.sort !== "relevance") p.set("sort", state.sort);
  if (state.tags.length) p.set("tags", state.tags.join(","));
  const h = p.toString();
  history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
}

function score(e, words) {
  if (!words.length) return 0;
  const name = fold(e.name);
  let s = 0;
  for (const w of words) {
    if (!e._hay.includes(w)) return -1;
    s += name.includes(w) ? 10 : 0;
    s += (e.tags || []).some((t) => t.includes(w)) ? 4 : 0;
    s += fold(e.description).includes(w) ? 2 : 0;
  }
  return s + (e.featured ? 1 : 0) + (e.description ? 1 : 0);
}

function popularity(e) {
  return (e.reactions || 0) + (e.stars || 0);
}

function filtered() {
  const words = fold(state.q).split(/\s+/).filter(Boolean);
  const sources = state.source ? state.source.split(",") : null;
  const rows = [];
  for (const e of catalog.entries) {
    if (state.kind && e.kind !== state.kind) continue;
    if (sources && !sources.includes(e.source)) continue;
    if (state.tags.some((t) => !(e.tags || []).includes(t))) continue;
    const s = score(e, words);
    if (s < 0) continue;
    rows.push([s, e]);
  }
  const byName = (a, b) => a[1].name.localeCompare(b[1].name, undefined, { sensitivity: "base" });
  const sorters = {
    relevance: (a, b) => b[0] - a[0] || (b[1].featured ? 1 : 0) - (a[1].featured ? 1 : 0) ||
      (b[1].description ? 1 : 0) - (a[1].description ? 1 : 0) || byName(a, b),
    name: byName,
    posted: (a, b) => (b[1].date || "").localeCompare(a[1].date || "") || byName(a, b),
    added: (a, b) => (b[1].added || "").localeCompare(a[1].added || "") ||
      (b[1].date || "").localeCompare(a[1].date || "") || byName(a, b),
    popular: (a, b) => popularity(b[1]) - popularity(a[1]) || byName(a, b),
  };
  rows.sort(sorters[state.sort] || sorters.relevance);
  return { rows: rows.map((r) => r[1]), words };
}

function renderTags(visible) {
  const counts = {};
  for (const e of visible) for (const t of e.tags || []) counts[t] = (counts[t] || 0) + 1;
  const html = Object.keys(catalog.tags).map((t) => {
    const on = state.tags.includes(t);
    if (!on && !counts[t]) return "";
    return `<button class="tag${on ? " on" : ""}" data-tag="${esc(t)}" title="${esc(catalog.tags[t])}">${esc(t)}<span class="n">${counts[t] || 0}</span></button>`;
  }).join("");
  $("tags").innerHTML = html + (state.tags.length ? `<button class="tag clear" data-clear>clear tags</button>` : "");
}

function isNew(e) {
  if (!e.added || !(e.added_by || "").startsWith("ai-scan")) return false;
  return (Date.now() - Date.parse(e.added)) / 86400000 < NEW_DAYS;
}

function renderItem(e, words) {
  const meta = [];
  if (e.author) meta.push(`by ${highlight(e.author, words)}`);
  meta.push(`${esc(SOURCE_LABEL[e.source] || e.source)}${e.where ? ": " + highlight(e.where, words) : ""}`);
  if (e.date) meta.push(esc(e.date));
  if (e.reactions) meta.push(`👍 ${e.reactions}`);
  if (e.stars) meta.push(`★ ${e.stars}`);
  if (e.version) meta.push(`v${esc(e.version)}`);
  if (e.code && e.code !== e.url) meta.push(`<a href="${esc(e.code)}">code</a>`);
  const tags = (e.tags || []).map((t) => `<button class="tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("");
  const desc = e.description
    ? `<p class="desc">${highlight(e.description, words)}</p>`
    : `<p class="desc none">No description yet.</p>`;
  return `<li class="item">
    <h2><a href="${esc(e.url)}">${highlight(e.name, words)}</a>
      <span class="badge">${esc(KIND_LABEL[e.kind] || e.kind)}</span>
      ${isNew(e) ? '<span class="badge new">new</span>' : ""}
      ${e.featured ? '<span class="featured" title="Marked as a main script by its author">★ featured</span>' : ""}
    </h2>
    ${desc}
    <div class="meta">${meta.map((m) => `<span>${m}</span>`).join("")}${tags}</div>
  </li>`;
}

function render() {
  writeHash();
  const { rows, words } = filtered();
  renderTags(rows);
  $("count").textContent = rows.length === catalog.entries.length
    ? `${rows.length} entries`
    : `${rows.length} of ${catalog.entries.length} entries`;
  $("results").innerHTML = rows.map((e) => renderItem(e, words)).join("");
  for (const b of $("kind").children) b.classList.toggle("on", b.dataset.v === state.kind);
}

function toggleTag(t) {
  state.tags = state.tags.includes(t) ? state.tags.filter((x) => x !== t) : [...state.tags, t];
  render();
}

document.addEventListener("click", (ev) => {
  const tag = ev.target.closest("[data-tag]");
  if (tag) return toggleTag(tag.dataset.tag);
  if (ev.target.closest("[data-clear]")) { state.tags = []; return render(); }
  const kind = ev.target.closest("#kind button");
  if (kind) { state.kind = kind.dataset.v; render(); }
});

$("q").addEventListener("input", () => { state.q = $("q").value; render(); });
$("source").addEventListener("change", () => { state.source = $("source").value; render(); });
$("sort").addEventListener("change", () => { state.sort = $("sort").value; render(); });
window.addEventListener("hashchange", () => { readHash(); syncControls(); render(); });

function syncControls() {
  $("q").value = state.q;
  $("source").value = state.source;
  $("sort").value = state.sort;
}

fetch("data/catalog.json")
  .then((r) => r.json())
  .then((data) => {
    catalog = data;
    for (const e of catalog.entries) {
      e._hay = fold([e.name, e.description, e.author, e.where, (e.tags || []).join(" ")].join(" "));
    }
    const scanned = catalog.entries.filter((e) => (e.added_by || "").startsWith("ai-scan")).length;
    $("stats").textContent = `${catalog.entries.length} entries · ${scanned} found by the monthly forum scan · updated ${catalog.updated}`;
    readHash();
    syncControls();
    render();
  })
  .catch((err) => { $("stats").textContent = "Could not load data/catalog.json: " + err; });
