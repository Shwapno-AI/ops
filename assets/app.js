/* Operations Dashboard — sales, performance, outlet network, growth & momentum, data quality, embedded views */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ------------------------------------------------------------------ config
  const NAV = [
    { group: "", items: [["gm", "Growth & momentum"], ["on", "Outlet network"]] },
    { group: "Sales", items: [["overview", "Overview"], ["achievement", "Sales achievement"], ["growth", "Sales growth"], ["footfall", "Footfall and basket"], ["ranking", "Growth and degrowth"], ["category", "Category performance"]] },
    { group: "Performance", items: [["performance", "KPI performance"], ["loss", "Loss-making outlets"]] },
    { group: "Availability", items: [["avs", "Summary"], ["avk", "SKU wise"], ["avc", "Core"], ["avp", "Promo"], ["avv", "KVI"], ["ave", "E-Commerce"], ["avb", "By division, zonal and outlet"]] },
    { group: "Consumable and wastage", items: [["cw", "Overview"], ["cwl", "League tables"], ["cwx", "Exceptions"], ["cwb", "Benchmarks"], ["cwm", "Materials"], ["cwo", "Outlet register"]] },
    { group: "Connected dashboards", items: [["gpva", "GPVA% Tracker"], ["cc", "Credit Card Extra Amount"], ["vc", "Visit Compliance"], ["rcv", "Receiving"]] },
    { group: "System", items: [["dq", "Data quality"]] },
  ];
  const TITLES = Object.fromEntries(NAV.flatMap((g) => g.items.map(([k, t]) => [k, g.group === "Consumable and wastage" || g.group === "Availability" ? `${g.group}: ${t === "KVI" ? t : t.toLowerCase().replace("e-commerce", "E-Commerce").replace("sku", "SKU")}` : t])));
  const SALES_PAGES = new Set(["overview", "achievement", "growth", "footfall", "ranking"]);
  const PERIOD_PAGES = new Set([...SALES_PAGES, "category"]);
  const NET_PAGES = new Set(["gm", "on"]);
  const CW_PAGES = new Set(["cw", "cwl", "cwx", "cwb", "cwm", "cwo"]);
  const AV_PAGES = new Set(["avs", "avk", "avc", "avp", "avv", "ave", "avb"]);
  const FILTER_PAGES = new Set([...SALES_PAGES, "loss", ...NET_PAGES, ...CW_PAGES, ...AV_PAGES]);
  const EMBEDS = {
    gpva: { url: "https://outlet-wise-gpva.shwapno.app/", desc: "Outlet-wise GPVA% tracking." },
    cc: { url: "https://aftabz-lab.github.io/credit-card-extra-amount/", desc: "Credit card extra amount by outlet." },
    vc: { url: "https://aftabz-lab.github.io/visit-compliance-dashboard/", desc: "Outlet visit schedules and compliance." },
    rcv: { url: "https://aftabz-lab.github.io/receiving-dashboard-shwapno/", desc: "Outlet receiving dashboard." },
  };
  const DIMS = [["rl", "Regional leader"], ["zn", "Zonal"], ["div", "Division"], ["dis", "District"], ["fmt", "Outlet format"], ["own", "Ownership"], ["pnp", "PNP status"], ["loc", "Location type"]];
  // Extra outlet-master fields, filterable on the outlet network pages only.
  const NET_DIMS = [["area", "Area"], ["city", "Location type (Dv, Ds, T)"], ["floor", "Floor type"], ["shape", "Layout shape"]];
  const CW_DIMS = [["area", "Area"], ["crit", "Final criteria"]];
  const CW_LEVELS = { zone: "Zonal", regionalLeader: "Regional leader", division: "Division", district: "District", criteria: "Final criteria", outlet: "Outlet" };
  const LEVELS = [["rl", "Regional leader"], ["zn", "Zonal"], ["div", "Division"], ["dis", "District"], ["fmt", "Outlet format"], ["own", "Ownership"], ["outlet", "Outlet"]];
  const BANDS = [
    { k: "b100", label: "100% or more", cls: "good", min: 1 },
    { k: "b90", label: "90 to 99%", cls: "warn", min: 0.9 },
    { k: "b80", label: "80 to 89%", cls: "bad", min: 0.8 },
    { k: "b0", label: "Below 80%", cls: "crit", min: -Infinity },
  ];

  const S = { data: null, page: "overview", period: "tilldate", filters: {}, openDim: null, tables: {}, level: "rl", bands: new Set(), lastFocus: null,
    cmp: "y", scope: "all", trend: "all", kp: null, kl: "rho", kv: "rank", krho: null, klh: null, kfocus: null, pm: null, pbasis: "before", lage: "all", pstat: "all", plevel: "rl", ageDrill: null,
    net: null, netLoading: false, netErr: null, netMode: "through", netFrom: "", netTo: "",
    gdrill: {}, ov: { lvl: "rl", rl: null, zn: null }, lv: { lvl: "rl", rl: null, zn: null }, cwh: { lvl: "rl", rl: null, zn: null },
    cw: null, cwLoading: false, cwErr: null, cwCrit: null,
    av: null, avLoading: false, avErr: null, avv: { days: "2", nd: "", cat3: "", type: "all", level: "rl", kviOnly: "no", glevel: "zn", elevel: "outlet" },
    cwv: { from: "", to: "", compare: false, status: "all", statusMetric: "consumableRate", basis: "daily", rankDim: "zone", rankMetric: "consumableRate", moversMetric: "consumableRate", leagueDim: "zone", leagueMetric: "consumableRate", excMetric: "all", benchMetric: "consumableRate" },
    on: { league: "regionalHead", oversight: "regional", launch: "year", cols: "key", drill: null },
    gm: { quad: "regionalHead", mover: "regionalHead", dir: "gain", league: "regionalHead" } };
  DIMS.concat(NET_DIMS, CW_DIMS).forEach(([k]) => (S.filters[k] = new Set()));
  const dims = () => (NET_PAGES.has(S.page) ? DIMS.concat(NET_DIMS) : CW_PAGES.has(S.page) ? DIMS.concat(CW_DIMS) : AV_PAGES.has(S.page) ? DIMS.concat([["area", "Area"]]) : DIMS);
  let AFTER = [];

  // ------------------------------------------------------------------ format
  const isNum = (v) => typeof v === "number" && isFinite(v);
  function bdt(v) {
    if (!isNum(v)) return "—";
    const s = v < 0 ? "−" : "", a = Math.abs(v);
    return s + "৳" + (a >= 1e7 ? (a / 1e7).toFixed(2) + " Cr" : a >= 1e5 ? (a / 1e5).toFixed(2) + " Lac" : a >= 1e3 ? (a / 1e3).toFixed(1) + " K" : a.toFixed(0));
  }
  const exact = (v) => (isNum(v) ? (v < 0 ? "−" : "") + "৳" + Math.round(Math.abs(v)).toLocaleString("en-US") : "—");
  const int = (v) => (isNum(v) ? Math.round(v).toLocaleString("en-US") : "—");
  const pct = (v, d = 2) => (isNum(v) ? (v * 100).toFixed(d) + "%" : "—");
  const pp = (v) => (isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(2) + " pp" : "—");
  function delta(v, unit = "%") {
    if (!isNum(v)) return '<span class="flat" title="No comparison base">—</span>';
    if (unit === "%" && Math.abs(v) > 9.99) return '<span class="muted" title="Comparison base is too small to be meaningful">n/m</span>';
    const c = v > 0.00005 ? "up" : v < -0.00005 ? "down" : "flat";
    const arrow = c === "up" ? "▲" : c === "down" ? "▼" : "■";
    const txt = unit === "pp" ? pp(v) : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(2) + "%";
    return `<span class="${c}">${arrow} ${txt}</span>`;
  }
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fdate = (s, noYear) => { if (!s) return "—"; const [y, m, d] = s.split("-").map(Number); return `${d} ${MON[m - 1]}${noYear ? "" : " " + y}`; };
  const fmonth = (s) => { const [y, m] = s.split("-").map(Number); return `${MON[m - 1]} ${y}`; };
  const ratio = (n, d) => (isNum(n) && d > 0 ? n / d : null);
  const growth = (n, d) => (isNum(n) && d > 0 ? n / d - 1 : null);
  const band = (v) => (isNum(v) ? BANDS.find((b) => v >= b.min) : { k: "none", label: "No target", cls: "idle" });
  const chip = (b) => `<span class="chip ${b.cls}">${esc(b.label)}</span>`;

  // ------------------------------------------------------------------ data
  function prep(d) {
    const M = {};
    (d.master?.outlets || []).forEach((o) => (M[o.c] = o));
    ["tilldate", "monthend"].forEach((k) => {
      if (!d[k]) return;
      d[k].outlets.forEach((o) => {
        mkDim(o, M[o.c], o.s > 0 || o.t > 0 ? "Not in outlet master" : "Closed outlets");
        o.nm = o.m?.n || String(o.name || o.c).replace(new RegExp("^" + o.c + "\\s*-\\s*"), "");
      });
    });
    Object.values(d.pnl?.summary || {}).forEach((list) => list.forEach((o) => { mkDim(o, M[o.c], o.s >= 1 ? "Not in outlet master" : "Closed outlets"); o.nm = o.n || o.m?.n || o.c; }));
  }
  function mkDim(o, m, miss) {
    o.m = m;
    o.dim = {
      rl: m?.rl || o.rl || miss, zn: m?.zn || o.zn || miss, div: m?.div || miss, dis: m?.dis || miss,
      fmt: m?.fmt || miss, own: m?.own || miss, pnp: m?.pnp || miss, loc: m?.loc || miss,
    };
  }
  const rep = () => S.data?.[S.period];
  const matches = (o, skip) => dims().every(([k]) => k === skip || !S.filters[k].size || S.filters[k].has(o.dim[k]));
  const baseList = () => (NET_PAGES.has(S.page) ? netRows() : CW_PAGES.has(S.page) ? S.cw?.outlets || [] : AV_PAGES.has(S.page) ? S.av?.outlets || [] : S.page === "loss" ? pnlList() : rep()?.outlets || []);
  const inView = () => baseList().filter((o) => matches(o) && (S.page !== "loss" || lossAgeOk(o)));
  // Loss page outlet-age filter: open a year or more, or under a year (outlets without an opening date only under All).
  function lossAgeOk(o) {
    if (S.lage === "all") return true;
    const a = pnlCalc(o).age;
    return a != null && (S.lage === "old" ? a >= 12 : a < 12);
  }
  function pnlList() {
    const P = S.data?.pnl;
    if (!P) return [];
    if (S.pm === "ytd" && P.months.length > 1) return pnlYtd();
    if (!P.summary[S.pm]) S.pm = P.months[P.months.length - 1];
    return P.summary[S.pm];
  }
  let ytdCache = null;
  function pnlYtd() {
    if (ytdCache) return ytdCache;
    const P = S.data.pnl, byC = new Map();
    P.months.forEach((m) => P.summary[m].forEach((o) => {
      const x = byC.get(o.c) || { c: o.c, s: 0, gp: 0, oi: 0, ox: 0, g: 0, ofc: 0, p: 0, ff: 0, months: 0 };
      ["s", "gp", "oi", "ox", "g", "ofc", "p", "ff"].forEach((k) => (x[k] += o[k] || 0));
      x.months++; x.n = o.n; x.nm = o.nm; x.ld = o.ld; x.sft = o.sft; x.m = o.m; x.dim = o.dim;
      byC.set(o.c, x);
    }));
    byC.forEach((x) => { x.bs = x.ff ? x.s / x.ff : null; if (!(x.s >= 1)) mkDim(x, x.m, "Closed outlets"); });
    return (ytdCache = [...byC.values()]);
  }
  function detailFor(code) {
    const P = S.data.pnl;
    if (S.pm !== "ytd") return P.detail?.[S.pm]?.[code] || null;
    let out = null;
    P.months.forEach((m) => { const d = P.detail?.[m]?.[code]; if (d) { out = out || d.map(() => 0); d.forEach((v, i) => (out[i] += v || 0)); } });
    return out;
  }

  function agg(list) {
    // a = achieved by outlets that have a target, so achievement is always achieved / target on the same outlets.
    // Sales of outlets without a target are kept apart in aNo (count nNo); aAll is everything.
    const a = { n: list.length, t: 0, a: 0, aAll: 0, aNo: 0, nNo: 0, tn: 0, s: 0, sy: 0, sm: 0, f: 0, fy: 0, fm: 0, gv: 0, gvy: 0, gvm: 0, ssS: 0, ssY: 0, ssn: 0 };
    for (const o of list) {
      a.t += o.t || 0; a.aAll += o.a || 0;
      if (o.t > 0) { a.tn++; a.a += o.a || 0; } else if (o.a) { a.aNo += o.a; a.nNo++; }
      a.s += o.s || 0; a.sy += o.sy || 0; a.sm += o.sm || 0;
      a.f += o.f || 0; a.fy += o.fy || 0; a.fm += o.fm || 0;
      a.gv += o.gv || 0; a.gvy += o.gvy || 0; a.gvm += o.gvm || 0;
      if (o.ssy) { a.ssS += o.s || 0; a.ssY += o.sy || 0; a.ssn++; }
    }
    a.ach = ratio(a.a, a.t);
    a.gy = growth(a.s, a.sy); a.gm = growth(a.s, a.sm); a.gss = growth(a.ssS, a.ssY);
    a.bk = ratio(a.s, a.f); a.bky = ratio(a.sy, a.fy);
    a.gp = ratio(a.gv, a.s); a.gpy = ratio(a.gvy, a.sy);
    const r = rep();
    if (r && !r.closed) {
      a.perDay = a.a / r.day;
      a.monthTarget = (a.t / r.day) * r.dim;
      a.projected = a.perDay * r.dim;
      a.needPerDay = r.dim > r.day ? Math.max(0, a.monthTarget - a.a) / (r.dim - r.day) : null;
    }
    return a;
  }

  // ------------------------------------------------------------------ table component
  function mountTable(id, spec) {
    S.tables[id] = S.tables[id] || { sort: spec.defaultSort, dir: spec.defaultDir || "desc", page: 1, q: "" };
    S.tables[id].spec = spec;
    return `<section class="panel" id="t-${id}"></section>`;
  }
  function tableRows(id) {
    const t = S.tables[id], sp = t.spec;
    let rows = sp.rows;
    if (t.q) {
      const q = t.q.toLowerCase();
      rows = rows.filter((r) => sp.searchText(r).toLowerCase().includes(q));
    }
    const col = sp.cols.find((c) => c.k === t.sort);
    if (col) {
      const v = col.val || ((r) => r[col.k]);
      rows = [...rows].sort((x, y) => {
        const a = v(x), b = v(y);
        const an = a == null || (typeof a === "number" && !isFinite(a)), bn = b == null || (typeof b === "number" && !isFinite(b));
        if (an || bn) return an && bn ? 0 : an ? 1 : -1;
        const c = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
        return (t.dir === "asc" ? c : -c) || String(sp.key(x)).localeCompare(String(sp.key(y)));
      });
    }
    return rows;
  }
  function drawTable(id) {
    const el = $("#t-" + id);
    if (!el) return;
    const t = S.tables[id], sp = t.spec, rows = tableRows(id);
    const size = sp.pageSize || 50, pages = Math.max(1, Math.ceil(rows.length / size));
    t.page = Math.min(t.page, pages);
    const slice = rows.slice((t.page - 1) * size, t.page * size);
    const shown = sp.cols.filter((c) => !c.hide);
    const th = shown.map((c) => {
      const active = t.sort === c.k;
      const arrow = active ? (t.dir === "asc" ? "↑" : "↓") : "↕";
      return `<th class="${c.num ? "num" : ""}" scope="col"><button class="sort-button${active ? " active" : ""}" data-sort="${c.k}">${esc(c.label)}<span>${arrow}</span></button></th>`;
    }).join("");
    const body = slice.length
      ? slice.map((r) => `<tr ${sp.rowAttr ? sp.rowAttr(r) : ""}>${shown.map((c) => `<td class="${c.num ? "num" : ""}">${c.fmt ? c.fmt(r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${shown.length}" class="empty">${esc(sp.empty || "No rows match the selected filters.")}</td></tr>`;
    const had = document.activeElement?.dataset?.tsearch === id;
    el.innerHTML = `
      <div class="panel-head"><div><h2>${esc(sp.title)}</h2><p>${esc(sp.desc(rows.length))}</p></div>
        <div class="panel-tools">${sp.tools || ""}<input class="search" type="search" placeholder="Search" aria-label="Search table" data-tsearch="${id}" value="${esc(t.q)}"><button class="btn" data-csv="${id}">Download CSV</button></div></div>
      ${sp.banner || ""}<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>
      ${rows.length > size ? `<div class="pager"><span>Showing ${int((t.page - 1) * size + 1)}–${int(Math.min(t.page * size, rows.length))} of ${int(rows.length)}</span><div><button class="btn" data-pg="-1" ${t.page === 1 ? "disabled" : ""}>Previous</button><span>Page ${t.page} of ${pages}</span><button class="btn" data-pg="1" ${t.page === pages ? "disabled" : ""}>Next</button></div></div>` : ""}`;
    $$("[data-sort]", el).forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.sort;
      if (t.sort === k) t.dir = t.dir === "asc" ? "desc" : "asc"; else { t.sort = k; t.dir = sp.cols.find((c) => c.k === k)?.firstDir || "desc"; }
      drawTable(id);
    }));
    const inp = $("[data-tsearch]", el);
    inp.addEventListener("input", () => { t.q = inp.value; t.page = 1; drawTable(id); });
    if (had) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    $$("[data-pg]", el).forEach((b) => b.addEventListener("click", () => { t.page += +b.dataset.pg; drawTable(id); }));
    $("[data-csv]", el).addEventListener("click", () => csv(id, rows));
    sp.wire && sp.wire(el);
    wireDyn(el);
  }
  function csv(id, rows) {
    const sp = S.tables[id].spec;
    const q = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const cols = (sp.csvCols || sp.cols).filter((c) => !c.nocsv);
    const lines = [cols.map((c) => q(c.csvLabel || c.label)).join(",")].concat(rows.map((r) => cols.map((c) => q(c.csv ? c.csv(r) : r[c.k])).join(",")));
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${sp.file}_${sp.stamp || rep()?.date || "data"}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ------------------------------------------------------------------ shell
  // Sidebar groups collapse and expand from their heading; the choice is remembered per browser.
  function renderNav() {
    const pick = UI.navOpen || {};
    $("#nav").innerHTML = NAV.map((g, gi) => {
      const items = g.items.map(([k, t, soon]) =>
        `<button data-page="${k}" ${S.page === k ? 'aria-current="page"' : ""}>${esc(t)}${soon ? '<span class="soon">Phase 2</span>' : ""}</button>`).join("");
      if (!g.group) return items;
      const open = pick[g.group] ?? g.items.some(([k]) => k === S.page);
      return `<button class="nav-group" data-navgroup="${esc(g.group)}" aria-expanded="${open}" aria-controls="navg${gi}"><span>${esc(g.group)}</span><span class="nav-caret" aria-hidden="true">${open ? "▾" : "▸"}</span></button>
        <div class="nav-items" id="navg${gi}"${open ? "" : " hidden"}>${items}</div>`;
    }).join("");
    $$("#nav [data-page]").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.page; closeRail(); }));
    $$("#nav [data-navgroup]").forEach((b) => b.addEventListener("click", () => {
      UI.navOpen = { ...(UI.navOpen || {}), [b.dataset.navgroup]: b.getAttribute("aria-expanded") !== "true" };
      saveUI(); renderNav();
    }));
  }
  // Sidebar and filter visibility, remembered per browser.
  const UI = { railHidden: false, filtersHidden: false, cwBarOpen: false, avBarOpen: false, navOpen: {} };
  try { Object.assign(UI, JSON.parse(localStorage.getItem("opsdash-ui") || "{}")); } catch (e) {}
  const saveUI = () => { try { localStorage.setItem("opsdash-ui", JSON.stringify(UI)); } catch (e) {} };
  function toggleFilters() { UI.filtersHidden = !UI.filtersHidden; S.openDim = null; saveUI(); renderFilters(); }
  function applyRail() {
    $(".shell").classList.toggle("rail-hidden", UI.railHidden);
    const b = $("#railBtn");
    b.textContent = UI.railHidden ? "☰" : "⇤";
    b.setAttribute("aria-label", UI.railHidden ? "Show sidebar" : "Hide sidebar");
    b.title = UI.railHidden ? "Show sidebar" : "Hide sidebar";
    b.setAttribute("aria-expanded", String(!UI.railHidden));
  }
  function renderFilters() {
    const base = baseList();
    const el = $("#filters");
    const prevDim = el.querySelector(".ms-panel")?.closest(".ms")?.dataset.dim;
    const same = prevDim === S.openDim;
    const keepScroll = same ? el.querySelector(".ms-list")?.scrollTop || 0 : 0;
    const keepQ = same ? el.querySelector(".ms-panel input")?.value || "" : "";
    const active = dims().reduce((n, [k]) => n + S.filters[k].size, 0);
    const head = `<div class="filters-head"><h2>Filters</h2><button class="btn" data-ftoggle aria-expanded="${!UI.filtersHidden}">${UI.filtersHidden ? "Show" : "Hide"}</button></div>`;
    if (UI.filtersHidden) {
      el.innerHTML = head + `<p class="filters-note">${active ? `${active} filter${active === 1 ? "" : "s"} applied` : "No filters applied"}</p>`;
      $("[data-ftoggle]", el).onclick = toggleFilters;
      $("#railFoot").innerHTML = base.length ? `${int(inView().length)} of ${int(base.length)} outlets in view` : "";
      return;
    }
    el.innerHTML = head + dims().map(([k, label]) => {
      const counts = new Map();
      base.forEach((o) => { if (matches(o, k)) counts.set(o.dim[k], (counts.get(o.dim[k]) || 0) + 1); });
      S.filters[k].forEach((v) => { if (!counts.has(v)) counts.set(v, 0); });
      const opts = [...counts.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0])));
      const sel = S.filters[k];
      const btnTxt = !sel.size ? "All" : sel.size === 1 ? [...sel][0] : sel.size + " selected";
      const open = S.openDim === k;
      return `<div class="ms" data-dim="${k}">
        <div class="ms-label"><span>${esc(label)}</span>${sel.size ? `<span class="ms-count">${sel.size}</span>` : ""}</div>
        <button class="ms-btn${sel.size ? " active" : ""}" aria-expanded="${open}" data-ms="${k}"><span>${esc(btnTxt)}</span><span>▾</span></button>
        ${open ? `<div class="ms-panel">
          ${opts.length > 8 ? `<input class="search" type="search" placeholder="Search ${esc(label.toLowerCase())}" aria-label="Search ${esc(label)}" value="${esc(keepQ)}">` : ""}
          <div class="ms-tools"><button data-all>Select all</button><button data-clear>Clear</button><span>${sel.size} selected / ${opts.length} available</span></div>
          <div class="ms-list" role="listbox" aria-multiselectable="true" aria-label="${esc(label)}">
            ${opts.map(([v, n]) => `<label class="ms-opt" role="option" aria-selected="${sel.has(v)}"><input type="checkbox" value="${esc(v)}" ${sel.has(v) ? "checked" : ""}><span>${esc(v)}</span><small>${n}</small></label>`).join("")}
          </div></div>` : ""}
      </div>`;
    }).join("");
    $("[data-ftoggle]", el).onclick = toggleFilters;
    $$("[data-ms]", el).forEach((b) => b.addEventListener("click", () => { S.openDim = S.openDim === b.dataset.ms ? null : b.dataset.ms; renderFilters(); }));
    const panel = $(".ms-panel", el);
    if (panel) {
      const k = S.openDim, list = $(".ms-list", panel);
      list.scrollTop = keepScroll;
      const search = $("input.search", panel);
      const applyQ = () => { const q = (search?.value || "").toLowerCase(); $$(".ms-opt", list).forEach((o) => (o.hidden = !o.textContent.toLowerCase().includes(q))); };
      if (search) { search.addEventListener("input", applyQ); applyQ(); }
      $$("input[type=checkbox]", list).forEach((c) => c.addEventListener("change", () => { c.checked ? S.filters[k].add(c.value) : S.filters[k].delete(c.value); changed(); }));
      $("[data-all]", panel).addEventListener("click", () => { $$(".ms-opt", list).filter((o) => !o.hidden).forEach((o) => S.filters[k].add($("input", o).value)); changed(); });
      $("[data-clear]", panel).addEventListener("click", () => { S.filters[k].clear(); changed(); });
    }
    $("#railFoot").innerHTML = base.length ? `${int(inView().length)} of ${int(base.length)} outlets in view` : "";
  }
  function renderPills() {
    const pills = [];
    dims().forEach(([k, label]) => S.filters[k].forEach((v) => pills.push(`<span class="filter-pill">${esc(label)}: ${esc(v)}<button aria-label="Remove ${esc(v)}" data-k="${k}" data-v="${esc(v)}">×</button></span>`)));
    $("#pills").innerHTML = pills.join("");
    $$("#pills button").forEach((b) => b.addEventListener("click", () => { S.filters[b.dataset.k].delete(b.dataset.v); changed(); }));
  }
  function renderTop() {
    $("#pageTitle").textContent = TITLES[S.page] || "Overview";
    const d = S.data, showP = PERIOD_PAGES.has(S.page);
    $("#periodSeg").hidden = !showP;
    $("#resetBtn").hidden = !FILTER_PAGES.has(S.page);
    if (d) {
      const opts = [["tilldate", d.tilldate && `Till ${fdate(d.tilldate.date, true)}`], ["monthend", d.monthend && `Last month, ${fmonth(d.monthend.date)}`]].filter((o) => o[1]);
      $("#periodSeg").innerHTML = opts.map(([k, t]) => `<button aria-pressed="${S.period === k}" data-period="${k}">${esc(t)}</button>`).join("");
      $$("#periodSeg button").forEach((b) => b.addEventListener("click", () => { S.period = b.dataset.period; changed(); }));
      const when = (t) => new Date(t).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dhaka" }).replace("Sept", "Sep");
      const fresh = (upTo, t) => { $("#fresh").textContent = `${upTo ? upTo + " · " : ""}updated ${when(t)}`; $("#fresh").title = "When the data was last refreshed from Google Drive"; };
      const r0 = rep();
      fresh(S.page === "performance" && d.kpi?.months?.length ? `KPI ${fmonth(d.kpi.months[d.kpi.months.length - 1])}` : S.page === "loss" && d.pnl ? `P&L ${fmonth(d.pnl.months[d.pnl.months.length - 1])}` : r0 ? `Data to ${fdate(r0.date, true)}` : "", d.generated);
      if (AV_PAGES.has(S.page)) {
        const a = S.av;
        if (a) { const st = (a.files || []).find((f) => f.kind === "stock"); fresh(st?.modified ? `Stock ${fdate(st.modified.slice(0, 10), true)}` : "", a.generatedAt); }
        $("#scope").textContent = a ? `${avDays()} day${avDays() === 1 ? "" : "s"} of cover. ${int(inView().length)} of ${int(baseList().length)} outlets in view.` : "";
        return;
      }
      if (CW_PAGES.has(S.page)) {
        const c = S.cw;
        if (c) fresh(c.dateRange?.max ? `Data to ${fdate(c.dateRange.max, true)}` : "", c.generatedAt);
        $("#scope").textContent = c ? `${fdate(S.cwv.from)} to ${fdate(S.cwv.to)}. ${int(inView().length)} of ${int(baseList().length)} outlets in view.` : "";
        return;
      }
      if (NET_PAGES.has(S.page)) {
        const n = S.net;
        if (n && driveNote()) $("#fresh").textContent = "Drive data " + driveNote();
        $("#scope").textContent = n ? `${fmonth(n.month)}, sales through ${fdate(S.netTo)}. ${int(inView().length)} of ${int(baseList().length)} outlets in view.` : "";
        return;
      }
      const r = rep();
      $("#scope").textContent = S.page === "loss" && d.pnl ? `Outlet P&L for ${S.pm === "ytd" ? "the year to date" : fmonth(S.pm || d.pnl.months[d.pnl.months.length - 1])}. ${int(inView().filter((o) => o.s >= 1).length)} trading outlets in view${S.lage === "old" ? ", open 1 year or more" : S.lage === "new" ? ", open under 1 year" : ""}.` : showP && r ? `${r.closed ? "Closed month" : "Month to date"}, ${r.splm_label?.replace(/^Same Day SPLM\s*/i, "") || fdate(r.date)}.${SALES_PAGES.has(S.page) ? ` ${int(inView().length)} outlets in view.` : " Company-wide figures."}` : "";
    }
  }
  function changed() {
    Object.values(S.tables).forEach((t) => (t.page = 1));
    render();
  }

  // ------------------------------------------------------------------ pages
  function kpi({ label, value, sub = "", foot = "", accent = "var(--info)", hero = false }) {
    return `<div class="kpi${hero ? " hero" : ""}" style="--accent:${accent}"><span class="label" title="${String(label).replace(/<[^>]*>/g, "").replace(/"/g, "&quot;")}">${label}</span><span class="value">${value}</span>${sub ? `<span class="sub">${sub}</span>` : ""}${foot ? `<span class="foot">${foot}</span>` : ""}</div>`;
  }
  function heroAchievement(a, r) {
    const b = band(a.ach), fill = Math.min(1, a.ach || 0) * 100;
    const pace = r.closed ? `<span>Closed month, final result</span>` : `<span>Now ${bdt(a.perDay)}/day</span><span>Needs ${bdt(a.needPerDay)}/day for ${r.dim - r.day} days</span>`;
    return kpi({
      hero: true, label: r.closed ? "Sales achievement, full month" : `Sales achievement, till ${fdate(r.date)}`, value: pct(a.ach),
      sub: `${chip(b)}<span>${bdt(a.a)} of ${bdt(a.t)} target</span>`,
      foot: `<div class="bar" style="flex:1 1 100%;margin:2px 0 6px" role="img" aria-label="Achievement ${pct(a.ach)}"><i style="width:${fill}%;background:var(--${b.cls})"></i></div>${pace}${a.nNo ? `<span title="Not counted in achievement">+${bdt(a.aNo)} from ${int(a.nNo)} outlet${a.nNo === 1 ? "" : "s"} without a target</span>` : ""}`,
    });
  }
  function bandsPanel(list) {
    const counts = Object.fromEntries(BANDS.map((b) => [b.k, 0])); let none = 0;
    list.forEach((o) => { const v = o.t > 0 ? (o.a || 0) / o.t : null; v == null ? none++ : counts[band(v).k]++; });
    const tot = list.length - none || 1;
    return `<section class="panel"><div class="panel-head"><div><h2>Outlets by achievement</h2><p>${int(list.length - none)} outlets with a target${none ? `, ${none} without` : ""}</p></div></div>
      <div class="panel-body bands">${BANDS.map((b) => `<div class="band-row"><span>${chip(b)}</span><div class="bar" style="--c:var(--${b.cls})"><i style="width:${(counts[b.k] / tot) * 100}%"></i></div><strong class="num" style="text-align:right">${int(counts[b.k])}</strong></div>`).join("")}
      <button class="btn" data-go="achievement" style="align-self:flex-start;margin-top:4px">Open sales achievement</button></div></section>`;
  }
  function levelRows(list, level) {
    const g = new Map();
    list.forEach((o) => { const k = level === "outlet" ? o.c : o.dim[level]; if (!g.has(k)) g.set(k, []); g.get(k).push(o); });
    return [...g.entries()].map(([k, os]) => {
      const a = agg(os), o = os[0];
      return level === "outlet"
        ? { key: k, name: o.nm, sub: `${o.c}, ${o.dim.zn}`, o, ...a }
        : { key: k, name: k, sub: `${int(os.length)} outlets`, ...a };
    });
  }
  function achCols(r, level) {
    const cols = [
      { k: "name", label: LEVELS.find((l) => l[0] === level)[1], fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name },
      { k: "t", label: "Target", num: 1, fmt: (x) => bdt(x.t), csv: (x) => Math.round(x.t) },
      { k: "a", label: "Achieved", num: 1, val: (x) => (x.o && !(x.t > 0) ? x.aAll : x.a), fmt: (x) => (x.o && !(x.t > 0) ? `${bdt(x.aAll)}<span class="cell-secondary">no target</span>` : `${bdt(x.a)}${x.nNo ? `<span class="cell-secondary" title="Not counted in achievement">+${bdt(x.aNo)} no target</span>` : ""}`), csv: (x) => Math.round(x.o && !(x.t > 0) ? x.aAll : x.a) },
      { k: "ach", label: "Achievement", num: 1, fmt: (x) => `<strong>${pct(x.ach)}</strong> ${chip(band(x.ach))}`, csv: (x) => (isNum(x.ach) ? (x.ach * 100).toFixed(2) : "") },
      { k: "gap", label: "Gap to target", num: 1, val: (x) => (x.t > 0 ? x.a - x.t : null), fmt: (x) => (x.t > 0 ? `<span class="${x.a - x.t < 0 ? "down" : "up"}">${bdt(x.a - x.t)}</span>` : "—"), csv: (x) => (x.t > 0 ? Math.round(x.a - x.t) : "") },
    ];
    if (!r.closed) cols.push(
      { k: "perDay", label: "Now per day", num: 1, fmt: (x) => bdt(x.perDay), csv: (x) => Math.round(x.perDay) },
      { k: "needPerDay", label: "Needed per day", num: 1, fmt: (x) => `<span class="${x.needPerDay > x.perDay ? "down" : ""}">${bdt(x.needPerDay)}</span>`, csv: (x) => Math.round(x.needPerDay ?? 0) },
    );
    cols.push(
      { k: "gy", label: "Growth vs last year", num: 1, fmt: (x) => delta(x.gy), csv: (x) => (isNum(x.gy) ? (x.gy * 100).toFixed(2) : "") },
      { k: "gm", label: "Growth vs last month", num: 1, fmt: (x) => delta(x.gm), csv: (x) => (isNum(x.gm) ? (x.gm * 100).toFixed(2) : "") },
    );
    if (level !== "outlet") cols.splice(1, 0, { k: "n", label: "Outlets", num: 1, fmt: (x) => int(x.n) });
    return cols;
  }
  const outletAttr = (x) => (x.o ? `data-outlet="${esc(x.o.c)}" tabindex="0"` : "");
  // Group drill: clicking a regional leader, zonal or other group row lists that group's outlets.
  // S.gdrill[tableId] = { level, key }; it only applies while the table is still grouped by that level.
  const levelName = (level) => (LEVELS.find((l) => l[0] === level) || [, CW_LEVELS[level] || NET_LEVELS[level] || AV_LEVELS[level] || level])[1];
  function gdrill(id, level) { const d = S.gdrill[id]; return d && d.level === level && level !== "outlet" ? d : null; }
  const gpickAttr = (id, level) => (x) => (x.o ? outletAttr(x) : `data-gpick="${esc(id)}" data-glevel="${esc(level)}" data-gkey="${esc(x.key)}" tabindex="0" title="List ${esc(x.name)}'s outlets"`);
  const gBanner = (id, d) => (d ? `<div class="drill-banner">Showing the outlets of <strong>${esc(AV_PAGES.has(S.page) ? AV_LEVELS[d.level] || levelName(d.level) : levelName(d.level))}: ${esc(d.key === "Not in outlet master" ? "Unassigned" : d.key)}</strong> within the sidebar filters. <button type="button" data-gclear="${esc(id)}">Back to all ${esc(AV_PAGES.has(S.page) && d.level === "rl" ? "RHOs" : (AV_PAGES.has(S.page) ? AV_LEVELS[d.level] || levelName(d.level) : levelName(d.level)).toLowerCase() + "s")}</button></div>` : "");

  // Three-level drill for leader tables: regional leader > zonal > outlet.
  // st is the state key in S ({ lvl, rl, zn }), id the table id, list the outlets (each with .dim) used to map zonals to leaders.
  function leaderDrill(st, id, list, hint, get = { rl: (o) => o.dim.rl, zn: (o) => o.dim.zn }) {
    const V = S[st], rlOf = {};
    list.forEach((o) => { const z = get.zn(o); if (z && !rlOf[z]) rlOf[z] = get.rl(o); });
    const at = V.zn ? "outlet" : V.rl ? "zn" : V.lvl;
    const d = `data-dst="${st}" data-dtab="${id}"`;
    const btn = (k, t) => `<button type="button" ${d} data-dlvl="${k}" aria-pressed="${!V.rl && !V.zn && V.lvl === k}">${t}</button>`;
    return {
      V, at, rlOf,
      inPath: (o) => (!V.rl || get.rl(o) === V.rl) && (!V.zn || get.zn(o) === V.zn),
      tools: `<div class="seg" role="group" aria-label="Level">${btn("rl", "Regional leaders")}${btn("zn", "Zonal leaders")}${btn("outlet", "Outlets")}</div>`,
      crumbs: V.rl || V.zn ? `<div class="drill-banner"><button type="button" ${d} data-dgo="top">${V.lvl === "zn" ? "Zonal leaders" : "Regional leaders"}</button>${V.rl ? ` › ${V.zn ? `<button type="button" ${d} data-dgo="rl">${esc(V.rl)}</button>` : `<strong>${esc(V.rl)}</strong>`}` : ""}${V.zn ? ` › <strong>${esc(V.zn)}</strong>` : ""}<span class="muted">· ${at === "zn" ? "click a zonal for its outlets" : hint}</span></div>` : "",
      pick: (x) => `${d} data-dpick="${at}" data-dkey="${esc(x.key)}" tabindex="0" title="${at === "rl" ? `See ${esc(x.name)}'s zonals` : `List ${esc(x.name)}'s outlets`}"`,
      zsub: (key, sub) => (V.rl ? sub : `${rlOf[key] || "—"} · ${sub}`),
      file: (base) => (V.zn ? `${base}_outlets_${V.zn}` : V.rl ? `${base}_zonals_${V.rl}` : `${base}_${{ rl: "regional_leaders", zn: "zonal_leaders", outlet: "outlets" }[at]}`).toLowerCase().replace(/[^a-z0-9_]+/g, "_"),
    };
  }

  // Overview top cards: titles in the same row get the height of the tallest one, so the numbers line up.
  // Cards in a grid row are already as tall as the tallest card, so this never makes a card taller.
  function alignKpiTitles() {
    const cards = $$(".ov-kpis .kpi:not(.hero)");
    cards.forEach((k) => (k.querySelector(".label").style.minHeight = ""));
    const rows = new Map();
    cards.forEach((k) => { const t = Math.round(k.getBoundingClientRect().top); rows.set(t, (rows.get(t) || []).concat(k)); });
    rows.forEach((ks) => { const h = Math.max(...ks.map((k) => k.querySelector(".label").getBoundingClientRect().height)); ks.forEach((k) => (k.querySelector(".label").style.minHeight = h + "px")); });
  }
  window.addEventListener("resize", () => S.page === "overview" && alignKpiTitles());
  function pageOverview() {
    const r = rep(), list = inView(), a = agg(list);
    if (!r) return `<p class="empty">No sales report is loaded yet. Check the Data quality page.</p>`;
    const top = levelRows(list.filter((o) => o.t > 0), "outlet");
    const best = [...top].sort((x, y) => y.ach - x.ach).slice(0, 10), worst = [...top].sort((x, y) => x.ach - y.ach).slice(0, 10);
    const mini = (title, rows) => `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p>By achievement against target</p></div></div>
      <div class="table-wrap"><table><thead><tr><th>Outlet</th><th class="num">Achieved</th><th class="num">Achievement</th><th class="num">vs last year</th></tr></thead><tbody>
      ${rows.map((x) => `<tr ${outletAttr(x)}><td><span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span></td><td class="num">${bdt(x.a)}</td><td class="num"><strong>${pct(x.ach)}</strong></td><td class="num">${delta(x.gy)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">No outlets match the selected filters.</td></tr>`}
      </tbody></table></div></section>`;
    const cats = r.categories || {};
    const catRows = (cats.sply || []).map((c) => ({ ...c, m: (cats.splm || []).find((x) => x.cat === c.cat) }));
    // Leaders table: regional leaders > zonals > outlets. Clicking a row goes one level down; the level switch picks the starting level.
    const D = leaderDrill("ov", "ov-league", list, "click an outlet for its profile"), at = D.at;
    let lrows = levelRows(list.filter(D.inPath), at);
    if (at === "zn") lrows = lrows.map((x) => ({ ...x, sub: D.zsub(x.key, x.sub) }));
    const league = mountTable("ov-league", {
      title: D.V.zn ? `Outlets of ${D.V.zn}` : D.V.rl ? `Zonals of ${D.V.rl}` : { rl: "Regional leaders", zn: "Zonal leaders", outlet: "Outlets" }[at], file: D.file("sales"), banner: D.crumbs, tools: D.tools,
      desc: (n) => (at === "outlet" ? `${n} outlet${n === 1 ? "" : "s"}. Click an outlet for its profile.` : at === "zn" ? `${n} zonal${n === 1 ? "" : "s"}. Achievement and growth for the outlets in view. Click a zonal to list its outlets.` : `${n} regional leaders. Achievement and growth for the outlets in view. Click a leader to see their zonals.`),
      rows: lrows, cols: achCols(r, at), key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "a", pageSize: 25,
      rowAttr: (x) => (x.o ? outletAttr(x) : D.pick(x)),
    });
    AFTER.push(alignKpiTitles);
    return `
      <div class="kpis ov-kpis">
        ${heroAchievement(a, r)}
        ${kpi({ label: "Sales growth vs last year", value: delta(a.gy), sub: "All stores", foot: `<span>${bdt(a.s)}</span><span>last year ${bdt(a.sy)}</span>`, accent: "var(--series-2)" })}
        ${kpi({ label: "Same-store growth vs last year", value: delta(a.gss), sub: `${int(a.ssn)} same stores`, foot: `<span>${bdt(a.ssS)}</span><span>last year ${bdt(a.ssY)}</span>`, accent: "var(--series-2)" })}
        ${kpi({ label: "Sales growth vs last month", value: delta(a.gm), sub: "All stores, same days", foot: `<span>${bdt(a.s)}</span><span>last month ${bdt(a.sm)}</span>`, accent: "var(--series-3)" })}
        ${kpi({ label: "Footfall vs last year", value: delta(growth(a.f, a.fy)), sub: "Customers, all stores", foot: `<span>${int(a.f)}</span><span>last year ${int(a.fy)}</span>`, accent: "var(--series-1)" })}
        ${kpi({ label: "Average bill value", value: bdt(a.bk), sub: delta(growth(a.bk, a.bky)) + " vs last year", foot: `<span>${bdt(a.bk)}</span><span>last year ${bdt(a.bky)}</span>`, accent: "var(--series-1)" })}
        ${kpi({ label: "Gross profit margin", value: pct(a.gp), sub: `${delta(isNum(a.gp) && isNum(a.gpy) ? a.gp - a.gpy : null, "pp")} vs last year ${pct(a.gpy)}`, foot: `<span>GP ${bdt(a.gv)}</span><span>last year ${bdt(a.gvy)}</span>`, accent: "var(--series-3)" })}
      </div>
      ${league}
      <div class="grid-h">${mini("Top 10 outlets", best)}${mini("Bottom 10 outlets", worst)}</div>
      <div class="grid-2">${catRows.length ? `<section class="panel"><div class="panel-head"><div><h2>Category growth</h2><p>Company-wide figures from the report. Filters don't apply here.</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">All stores vs last year</th><th class="num">Own same-store vs last year</th><th class="num">Franchise same-store vs last year</th><th class="num">All stores vs last month</th></tr></thead><tbody>
        ${catRows.map((c) => `<tr><td class="cell-primary">${esc(c.cat)}</td><td class="num">${delta(c.all)}</td><td class="num">${delta(c.own)}</td><td class="num">${delta(c.fran)}</td><td class="num">${delta(c.m?.all)}</td></tr>`).join("")}
        </tbody></table></div></section>` : ""}${bandsPanel(list)}</div>`;
  }

  function pageAchievement() {
    const r = rep();
    if (!r) return `<p class="empty">No sales report is loaded yet. Check the Data quality page.</p>`;
    const list = inView(), a = agg(list), ad = gdrill("ach", S.level), lv = ad ? "outlet" : S.level;
    let rows = ad ? levelRows(list.filter((o) => o.dim[S.level] === ad.key), "outlet") : levelRows(list, S.level);
    if (S.bands.size) rows = rows.filter((x) => S.bands.has(band(x.ach).k));
    const tools = `<select class="sel" data-level aria-label="Group by">${LEVELS.map(([k, t]) => `<option value="${k}" ${S.level === k ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      ${BANDS.concat([{ k: "none", label: "No target" }]).map((b) => `<button class="btn" aria-pressed="${S.bands.has(b.k)}" data-band="${b.k}">${esc(b.label)}</button>`).join("")}`;
    const lvlName = LEVELS.find((l) => l[0] === S.level)[1];
    const table = mountTable("ach", {
      title: `Achievement by ${lvlName.toLowerCase()}`, file: `achievement_by_${S.level}`,
      desc: (n) => `${int(n)} rows. ${r.closed ? "Final month results." : "Target is prorated to the days elapsed; needed per day assumes an even daily target."}${lv === "outlet" ? " Click a row for the outlet profile." : " Click a row to list its outlets."}`,
      rows, cols: achCols(r, lv), key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "a", tools, rowAttr: gpickAttr("ach", S.level), banner: gBanner("ach", ad),
      wire: (el) => {
        $("[data-level]", el).addEventListener("change", (e) => { S.level = e.target.value; S.tables.ach.page = 1; render(); });
        $$("[data-band]", el).forEach((b) => b.addEventListener("click", () => { const k = b.dataset.band; S.bands.has(k) ? S.bands.delete(k) : S.bands.add(k); S.tables.ach.page = 1; render(); }));
      },
    });
    const k = r.closed
      ? [kpi({ label: "Target", value: bdt(a.t), foot: `<span>${int(a.tn)} outlets with a target</span>` }), kpi({ label: "Achieved", value: bdt(a.a), foot: `<span>${exact(a.a)}</span>${a.nNo ? `<span>+${bdt(a.aNo)} without a target</span>` : ""}` }), kpi({ label: "Gap to target", value: bdt(a.a - a.t), foot: `<span>${a.a >= a.t ? "Above target" : "Below target"}</span>`, accent: `var(--${a.a >= a.t ? "good" : "bad"})` }), kpi({ label: "Average per day", value: bdt(a.a / r.dim), foot: `<span>${r.dim} trading days</span>` })]
      : [kpi({ label: "Projected month-end sales", value: bdt(a.projected), sub: "At the current daily pace", foot: `<span>Estimated month target ${bdt(a.monthTarget)}</span>` }),
         kpi({ label: "Needed per day", value: bdt(a.needPerDay), sub: `For the remaining ${r.dim - r.day} days`, foot: `<span>Now ${bdt(a.perDay)}/day</span>`, accent: `var(--${a.needPerDay > a.perDay ? "bad" : "good"})` }),
         kpi({ label: "Gap to till-date target", value: bdt(a.a - a.t), foot: `<span>${int(a.tn)} outlets with a target</span>`, accent: `var(--${a.a >= a.t ? "good" : "bad"})` }),
         kpi({ label: "Outlets at 100% or more", value: int(list.filter((o) => o.t > 0 && o.a >= o.t).length), foot: `<span>of ${int(a.tn)} with a target</span>`, accent: "var(--good)" })];
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">${heroAchievement(a, r)}${k.join("")}</div>${table}`;
  }

  function pageDQ() {
    const d = S.data;
    const lvl = { error: "bad", warn: "warn", info: "info" };
    const name = { error: "Problem", warn: "Warning", info: "Note" };
    const folder = { tilldate: "Till-date folder", monthend: "Month-end folder", performance: "Performance folder" };
    return `
      <section class="panel"><div class="panel-head"><div><h2>Files in use</h2><p>Recognised by their content. Filenames don't matter.</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>File</th><th>Type</th><th>Folder</th><th>Data up to</th></tr></thead><tbody>
        ${d.sources.map((s) => `<tr><td class="cell-primary">${esc(s.file)}</td><td>${esc(s.type)}</td><td>${esc(folder[s.folder] || s.folder)}</td><td>${/^\d{4}-\d{2}$/.test(s.date) ? esc(s.date) : fdate(s.date)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">No files were found in the Drive folders.</td></tr>`}
        </tbody></table></div></section>
      <section class="panel"><div class="panel-head"><div><h2>Checks from the last refresh</h2><p>${d.issues.filter((i) => i.level === "error").length} problems, ${d.issues.filter((i) => i.level === "warn").length} warnings</p></div></div>
        <div class="panel-body">${d.issues.map((i) => `<div class="issue"><span>${chip({ cls: lvl[i.level], label: name[i.level] })}</span><div>${esc(i.message)}<small>${esc(i.source)}</small></div></div>`).join("") || '<p class="muted">All checks passed.</p>'}</div></section>
      ${netFilesPanel()}
      ${cwQualityPanel()}
      ${avQualityPanel()}
      <section class="panel"><div class="panel-head"><div><h2>How updates work</h2></div></div>
        <div class="panel-body"><p style="margin:0;max-width:72ch">Upload or replace a file in its Google Drive folder. The dashboard checks the folders every hour between 8 am and 11 pm and refreshes on its own. To refresh straight away, open the repository on GitHub, go to Actions, choose "Refresh data" and press "Run workflow". If a file is broken, the dashboard keeps the last good data and the problem appears on this page.</p></div></section>`;
  }

  function pageEmbed(k) {
    const e = EMBEDS[k];
    return `<section class="panel embed"><div class="panel-head"><div><h2>${esc(TITLES[k])}</h2><p>${esc(e.desc)}</p></div>
      <div class="panel-tools"><a class="btn" href="${e.url}" target="_blank" rel="noopener">Open in new tab</a></div></div>
      <iframe src="${e.url}" title="${esc(TITLES[k])} dashboard" loading="lazy"></iframe></section>`;
  }

  // ------------------------------------------------------------------ shared helpers (growth pages)
  const CMP = { y: "last year", m: "last month" };
  const SCOPES = [["all", "All stores"], ["same", "Same store"], ["own", "Own"], ["fran", "Franchise"]];
  const noData = () => `<p class="empty">No sales report is loaded yet. Check the Data quality page.</p>`;
  function cagg(list, c) {
    let s = 0, s0 = 0, f = 0, f0 = 0, g = 0, g0 = 0;
    for (const o of list) { s += o.s || 0; s0 += o["s" + c] || 0; f += o.f || 0; f0 += o["f" + c] || 0; g += o.gv || 0; g0 += o["gv" + c] || 0; }
    const b = ratio(s, f), b0 = ratio(s0, f0), gp = ratio(g, s), gp0 = ratio(g0, s0);
    return { n: list.length, s, s0, f, f0, diff: s - s0, gs: growth(s, s0), gf: growth(f, f0), b, b0, gb: growth(b, b0), gp, gp0, gpd: isNum(gp) && isNum(gp0) ? gp - gp0 : null };
  }
  const inScope = (o, scope, c) => scope === "all" || (scope === "same" ? !!o["ss" + c] : scope === "own" ? o.dim.own === "Own" : o.dim.own === "Franchise");
  function groupRows(list, level, fn) {
    const g = new Map();
    list.forEach((o) => { const k = level === "outlet" ? o.c : o.dim[level]; if (!g.has(k)) g.set(k, []); g.get(k).push(o); });
    return [...g.entries()].map(([k, os]) => level === "outlet"
      ? { key: k, name: os[0].nm, sub: `${os[0].c}, ${os[0].dim.zn}`, o: os[0], ...fn(os) }
      : { key: k, name: k, sub: `${int(os.length)} outlets`, ...fn(os) });
  }
  const seg = (set, opts, label) => `<div class="seg" role="group" aria-label="${esc(label)}">${opts.map(([v, t]) => `<button data-set="${set}" data-val="${v}" aria-pressed="${S[set] === v}">${esc(t)}</button>`).join("")}</div>`;
  const levelSel = () => `<select class="sel" data-sel="level" aria-label="Group by">${LEVELS.map(([k, t]) => `<option value="${k}" ${S.level === k ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  const pcsv = (v) => (isNum(v) ? (v * 100).toFixed(2) : "");
  const nameCol = (level) => ({ k: "name", label: LEVELS.find((l) => l[0] === level)[1], fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name, val: (x) => x.name });
  const nCol = { k: "n", label: "Outlets", num: 1, fmt: (x) => int(x.n) };
  const cmpLabel = (r) => (S.cmp === "y" ? r.sply_label : r.splm_label) || "";
  const cmpSeg = () => seg("cmp", [["y", "vs last year"], ["m", "vs last month"]], "Compare with");

  function wireDyn(root) {
    // Panels with a CSV button: the description shows on hovering the title, so the tools stay on the right.
    $$(".panel-head", root).forEach((h) => {
      if (!h.querySelector("[data-csv],[data-ncsv]")) return;
      const t = h.querySelector(":scope > div > h2"), d = t && t.nextElementSibling;
      if (!t || t.classList.contains("hint-title") || !d || d.tagName !== "P" || !d.textContent.trim()) return;
      t.classList.add("hint-title"); t.tabIndex = 0;
      t.insertAdjacentHTML("beforeend", ' <span class="hint-i" aria-hidden="true">ⓘ</span>');
      d.classList.add("hint-text");
    });
    $$("[data-age-band]", root).forEach((b) => (b.onclick = () => openAgeOutlets(b.dataset.ageBand, b.dataset.ageScope === "loss")));
    $$("[data-outlet]", root).forEach((tr) => { tr.onclick = () => openOutlet(tr.dataset.outlet); tr.onkeydown = (e) => { if (e.key === "Enter") openOutlet(tr.dataset.outlet); }; });
    $$("[data-pnl]", root).forEach((tr) => { tr.onclick = () => openPnl(tr.dataset.pnl); tr.onkeydown = (e) => { if (e.key === "Enter") openPnl(tr.dataset.pnl); }; });
    $$("[data-khead]", root).forEach((tr) => { tr.onclick = (e) => { e.stopPropagation(); openHead(tr.dataset.khead); }; tr.onkeydown = (e) => { if (e.key === "Enter") { e.stopPropagation(); openHead(tr.dataset.khead); } }; });
    $$("[data-kmetric]", root).forEach((n) => { const go = (e) => { e.stopPropagation(); openKpiMetric(n.dataset.kmetric); }; n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter") go(e); }; });
    $$("[data-kband]", root).forEach((n) => { const go = () => openKpiBand(Number(n.dataset.kband)); n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("[data-kdrill]", root).forEach((n) => { const go = () => { S.kl = "zonal"; S.krho = n.dataset.kdrill; S.kfocus = ".k-mat"; changed(); }; n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("[data-kclear]", root).forEach((n) => (n.onclick = () => { S.krho = null; S.kfocus = n.closest(".k-mat") ? ".k-mat" : null; changed(); }));
    $$("[data-kback]", root).forEach((n) => (n.onclick = () => { S.kl = "rho"; S.krho = null; S.kfocus = n.closest(".k-mat") ? ".k-mat" : null; changed(); }));
    $$("[data-klh]", root).forEach((n) => { const go = () => { S.klh = n.dataset.klh; S.kfocus = ".k-lh"; changed(); }; n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("[data-kscroll]", root).forEach((b) => (b.onclick = () => { const box = b.closest(".panel")?.querySelector("[data-kcs]"), c = box?.firstElementChild; if (!c) return; const step = c.offsetHeight + 10; box.scrollTo({ top: (Math.round(box.scrollTop / step) + Number(b.dataset.kscroll)) * step, behavior: "smooth" }); }));
    $$("[data-kcs]", root).forEach((box) => {
      const lab = box.closest(".panel")?.querySelector("[data-kcn]");
      const upd = () => { const c = box.firstElementChild; if (!c || !lab) return; const cols = getComputedStyle(box).gridTemplateColumns.split(" ").length, n = Number(box.dataset.kcs), a = Math.round(box.scrollTop / (c.offsetHeight + 10)) * cols + 1; lab.textContent = `${a}–${Math.min(a + cols * 2 - 1, n)} of ${n}`; };
      box.onscroll = upd; upd();
    });
    $$("[data-set]", root).forEach((b) => (b.onclick = () => { S[b.dataset.set] = b.dataset.val; changed(); }));
    $$("[data-sel]", root).forEach((sel) => (sel.onchange = () => { S[sel.dataset.sel] = sel.value; changed(); }));
    $$("[data-go]", root).forEach((b) => (b.onclick = () => (location.hash = b.dataset.go)));
    $$("[data-lpick]", root).forEach((tr) => {
      const go = () => {
        const same = S.lossPick?.level === S.plevel && S.lossPick.key === tr.dataset.lpick;
        S.lossPick = same ? null : { level: S.plevel, key: tr.dataset.lpick };
        if (S.tables.loss) S.tables.loss.page = 1;
        render();
        if (!same) requestAnimationFrame(() => $("#t-loss")?.scrollIntoView({ behavior: "smooth", block: "start" }));
      };
      tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); };
    });
    $$("[data-lpick-clear]", root).forEach((b) => (b.onclick = () => { S.lossPick = null; render(); }));
    $$("[data-gpick]", root).forEach((tr) => {
      const go = () => {
        const id = tr.dataset.gpick, cur = S.gdrill[id], same = cur && cur.level === tr.dataset.glevel && cur.key === tr.dataset.gkey;
        if (same) delete S.gdrill[id]; else S.gdrill[id] = { level: tr.dataset.glevel, key: tr.dataset.gkey };
        if (S.tables[id]) { S.tables[id].page = 1; S.tables[id].q = ""; }
        render();
        if (!same) requestAnimationFrame(() => $("#t-" + id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
      };
      tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); };
    });
    $$("[data-gclear]", root).forEach((b) => (b.onclick = () => { delete S.gdrill[b.dataset.gclear]; render(); }));
    $$("[data-lreason]", root).forEach((b) => (b.onclick = () => openLossReason(b.dataset.lreason, b.dataset.lrl)));
    $$("[data-lstat]", root).forEach((n) => { const go = (e) => { e.stopPropagation(); openLossStatus(n.dataset.lstat); }; n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter" && e.target === n) go(e); }; });
    // Leader tables (leaderDrill): level switch, drill down a level, breadcrumb back.
    // Re-render in place; only bring the table back into view when its title has scrolled above the header.
    const dGo = (n, follow) => {
      const id = n.dataset.dtab; if (S.tables[id]) { S.tables[id].page = 1; S.tables[id].q = ""; }
      const y = scrollY; render(); scrollTo(0, y);
      if (!follow) return;
      requestAnimationFrame(() => { const el = $("#t-" + id), top = $(".topbar")?.offsetHeight || 0; if (el && el.getBoundingClientRect().top < top) scrollTo(0, scrollY + el.getBoundingClientRect().top - top - 12); });
    };
    $$("[data-dlvl]", root).forEach((b) => (b.onclick = () => { S[b.dataset.dst] = { lvl: b.dataset.dlvl, rl: null, zn: null }; dGo(b); }));
    $$("[data-dpick]", root).forEach((tr) => {
      const go = () => { const V = S[tr.dataset.dst]; if (tr.dataset.dpick === "rl") V.rl = tr.dataset.dkey; else V.zn = tr.dataset.dkey; dGo(tr, true); };
      tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); };
    });
    $$("[data-dgo]", root).forEach((b) => (b.onclick = () => { const V = S[b.dataset.dst]; if (b.dataset.dgo === "top") { V.rl = null; V.zn = null; } else V.zn = null; dGo(b, true); }));
    $$("[data-uitoggle]", root).forEach((b) => (b.onclick = () => { UI[b.dataset.uitoggle] = !UI[b.dataset.uitoggle]; saveUI(); render(); }));
    wireNet(root);
    wireCw(root);
    wireAv(root);
  }

  // ------------------------------------------------------------------ sales growth
  function pageGrowth() {
    const r = rep(); if (!r) return noData();
    const c = S.cmp, list = inView();
    const card = (label, scope, accent) => {
      const a = cagg(list.filter((o) => inScope(o, scope, c)), c);
      return kpi({ label, value: delta(a.gs), sub: `${int(a.n)} outlets`, foot: `<span>${bdt(a.s)}</span><span>${CMP[c]} ${bdt(a.s0)}</span>`, accent });
    };
    const gd = gdrill("growth", S.level), lv = gd ? "outlet" : S.level;
    const rows = groupRows(list.filter((o) => inScope(o, S.scope, c) && (!gd || o.dim[S.level] === gd.key)), lv, (os) => cagg(os, c));
    const scopeName = SCOPES.find((x) => x[0] === S.scope)[1].toLowerCase();
    const cols = [nameCol(lv), ...(lv === "outlet" ? [] : [nCol]),
      { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s) },
      { k: "s0", label: `Sales ${CMP[c]}`, num: 1, fmt: (x) => bdt(x.s0), csv: (x) => Math.round(x.s0) },
      { k: "gs", label: "Growth", num: 1, fmt: (x) => delta(x.gs), csv: (x) => pcsv(x.gs) },
      { k: "diff", label: "Change", num: 1, fmt: (x) => `<span class="${x.diff < 0 ? "down" : "up"}">${bdt(x.diff)}</span>`, csv: (x) => Math.round(x.diff) },
      { k: "gp", label: "GP margin", num: 1, fmt: (x) => pct(x.gp), csv: (x) => pcsv(x.gp) },
      { k: "gpd", label: "GP margin change", num: 1, fmt: (x) => delta(x.gpd, "pp"), csv: (x) => pcsv(x.gpd) }];
    const table = mountTable("growth", {
      title: `Growth ${CMP[c] === "last year" ? "vs last year" : "vs last month"}, ${scopeName}`, file: `growth_${c}_${S.scope}_${S.level}`,
      desc: (n) => `${int(n)} rows. ${cmpLabel(r)}.${S.scope === "same" ? " Same store follows the report's own same-store list." : ""}${lv === "outlet" ? " Click a row for the outlet profile." : " Click a row to list its outlets."}`,
      rows, cols, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "gs", rowAttr: gpickAttr("growth", S.level), banner: gBanner("growth", gd),
      tools: `${cmpSeg()}${seg("scope", SCOPES, "Stores")}${levelSel()}`,
    });
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      ${card("All stores", "all", "var(--series-2)")}${card("Same store", "same", "var(--series-2)")}${card("Own outlets", "own", "var(--series-3)")}${card("Franchise outlets", "fran", "var(--series-3)")}
      </div>${table}`;
  }

  // ------------------------------------------------------------------ footfall & basket
  function pageFootfall() {
    const r = rep(); if (!r) return noData();
    const c = S.cmp, list = inView().filter((o) => inScope(o, S.scope, c)), a = cagg(list, c);
    const fd = gdrill("footfall", S.level), lv = fd ? "outlet" : S.level;
    const rows = groupRows(fd ? list.filter((o) => o.dim[S.level] === fd.key) : list, lv, (os) => cagg(os, c));
    const cols = [nameCol(lv), ...(lv === "outlet" ? [] : [nCol]),
      { k: "f", label: "Footfall", num: 1, fmt: (x) => int(x.f), csv: (x) => Math.round(x.f) },
      { k: "f0", label: `Footfall ${CMP[c]}`, num: 1, fmt: (x) => int(x.f0), csv: (x) => Math.round(x.f0) },
      { k: "gf", label: "Footfall growth", num: 1, fmt: (x) => delta(x.gf), csv: (x) => pcsv(x.gf) },
      { k: "b", label: "Bill value", num: 1, fmt: (x) => bdt(x.b), csv: (x) => (isNum(x.b) ? x.b.toFixed(2) : "") },
      { k: "b0", label: `Bill value ${CMP[c]}`, num: 1, fmt: (x) => bdt(x.b0), csv: (x) => (isNum(x.b0) ? x.b0.toFixed(2) : "") },
      { k: "gb", label: "Bill value growth", num: 1, fmt: (x) => delta(x.gb), csv: (x) => pcsv(x.gb) },
      { k: "gs", label: "Sales growth", num: 1, fmt: (x) => delta(x.gs), csv: (x) => pcsv(x.gs) }];
    const days = r.closed ? r.dim : r.day;
    const table = mountTable("footfall", {
      title: `Footfall and bill value ${S.cmp === "y" ? "vs last year" : "vs last month"}`, file: `footfall_${c}_${S.scope}_${S.level}`,
      desc: (n) => `${int(n)} rows. Bill value is sales divided by customers. ${cmpLabel(r)}.${lv === "outlet" ? " Click a row for the outlet profile." : " Click a row to list its outlets."}`,
      rows, cols, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "gf", rowAttr: gpickAttr("footfall", S.level), banner: gBanner("footfall", fd),
      tools: `${cmpSeg()}${seg("scope", SCOPES, "Stores")}${levelSel()}`,
    });
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      ${kpi({ label: "Footfall growth", value: delta(a.gf), sub: `${int(a.f)} customers`, foot: `<span>${CMP[c]} ${int(a.f0)}</span>`, accent: "var(--series-1)" })}
      ${kpi({ label: "Customers per day", value: int(a.f / days), sub: `Over ${days} days`, foot: `<span>${int(a.n)} outlets</span>`, accent: "var(--series-1)" })}
      ${kpi({ label: "Average bill value", value: bdt(a.b), sub: `${delta(a.gb)} vs ${CMP[c]}`, foot: `<span>${CMP[c]} ${bdt(a.b0)}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: "Sales growth", value: delta(a.gs), sub: "Footfall and bill value combined", foot: `<span>${bdt(a.s)}</span><span>${CMP[c]} ${bdt(a.s0)}</span>`, accent: "var(--series-3)" })}
      </div>${table}`;
  }

  // ------------------------------------------------------------------ growth & degrowth ranking
  const DRIVERS = { "More customers": "good", "Bigger baskets": "good", "Fewer customers": "bad", "Smaller baskets": "bad" };
  function driver(x) {
    if (!(x.f > 0 && x.f0 > 0 && x.b > 0 && x.b0 > 0)) return null;
    const lf = Math.log(x.f / x.f0), lb = Math.log(x.b / x.b0);
    return Math.abs(lf) >= Math.abs(lb) ? (lf >= 0 ? "More customers" : "Fewer customers") : (lb >= 0 ? "Bigger baskets" : "Smaller baskets");
  }
  function pageRanking() {
    const r = rep(); if (!r) return noData();
    const c = S.cmp, list = inView().filter((o) => inScope(o, S.scope, c));
    const comp = list.filter((o) => o.s > 0 && o["s" + c] > 0);
    const fresh = list.filter((o) => o.s > 0 && !(o["s" + c] > 0)).length, gone = list.filter((o) => !(o.s > 0) && o["s" + c] > 0).length;
    const rd = gdrill("rank", "rl");
    let rows = groupRows(rd ? comp.filter((o) => o.dim.rl === rd.key) : comp, "outlet", (os) => cagg(os, c));
    rows.forEach((x) => (x.drv = driver(x)));
    const grow = rows.filter((x) => x.gs > 0).length, dec = rows.filter((x) => x.gs < 0).length;
    if (S.trend === "up") rows = rows.filter((x) => x.gs > 0);
    if (S.trend === "down") rows = rows.filter((x) => x.gs < 0);
    const t1 = mountTable("rank", {
      title: "Outlet ranking", file: `growth_ranking_${c}_${S.trend}`, banner: gBanner("rank", rd),
      desc: (n) => `${int(n)} comparable outlets (sales in both periods). Main driver is whichever of footfall or bill value moved sales more. Click a row for the outlet profile.`,
      rows, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "gs", defaultDir: S.trend === "down" ? "asc" : "desc", rowAttr: outletAttr,
      tools: `${cmpSeg()}${seg("trend", [["all", "All"], ["up", "Growing"], ["down", "Declining"]], "Trend")}${seg("scope", SCOPES, "Stores")}`,
      cols: [nameCol("outlet"),
        { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s) },
        { k: "s0", label: `Sales ${CMP[c]}`, num: 1, fmt: (x) => bdt(x.s0), csv: (x) => Math.round(x.s0) },
        { k: "gs", label: "Growth", num: 1, fmt: (x) => delta(x.gs), csv: (x) => pcsv(x.gs) },
        { k: "diff", label: "Change", num: 1, fmt: (x) => `<span class="${x.diff < 0 ? "down" : "up"}">${bdt(x.diff)}</span>`, csv: (x) => Math.round(x.diff) },
        { k: "gf", label: "Footfall", num: 1, fmt: (x) => delta(x.gf), csv: (x) => pcsv(x.gf) },
        { k: "gb", label: "Bill value", num: 1, fmt: (x) => delta(x.gb), csv: (x) => pcsv(x.gb) },
        { k: "drv", label: "Main driver", fmt: (x) => (x.drv ? chip({ cls: DRIVERS[x.drv], label: x.drv }) : '<span class="muted">—</span>'), csv: (x) => x.drv || "" }],
    });
    const byRl = groupRows(comp, "rl", (os) => { const g = os.map((o) => cagg([o], c)); const up = g.filter((x) => x.gs > 0).length, dn = g.filter((x) => x.gs < 0).length; return { ...cagg(os, c), up, dn, share: os.length ? dn / os.length : null }; });
    const t2 = mountTable("rank-rl", {
      title: "Growing and declining outlets by regional leader", file: `growth_by_rl_${c}`, pageSize: 25,
      desc: (n) => `${n} regional leaders, comparable outlets only. Click a leader to list their outlets in the ranking.`, rows: byRl, key: (x) => x.key, searchText: (x) => x.name, defaultSort: "share",
      rowAttr: (x) => `data-gpick="rank" data-glevel="rl" data-gkey="${esc(x.key)}" data-gscroll="1" tabindex="0" title="List ${esc(x.name)}'s outlets"${rd && rd.key === x.key ? ' aria-selected="true"' : ""}`,
      cols: [nameCol("rl"), { k: "n", label: "Comparable outlets", num: 1, fmt: (x) => int(x.n) },
        { k: "up", label: "Growing", num: 1, fmt: (x) => `<span class="up">${int(x.up)}</span>` }, { k: "dn", label: "Declining", num: 1, fmt: (x) => `<span class="down">${int(x.dn)}</span>` },
        { k: "share", label: "Share declining", num: 1, fmt: (x) => pct(x.share), csv: (x) => pcsv(x.share) }, { k: "gs", label: "Growth", num: 1, fmt: (x) => delta(x.gs), csv: (x) => pcsv(x.gs) }],
    });
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      ${kpi({ label: "Growing outlets", value: int(grow), sub: `of ${int(grow + dec)} comparable`, foot: `<span>${pct((grow / (grow + dec || 1)))} of comparable outlets</span>`, accent: "var(--good)" })}
      ${kpi({ label: "Declining outlets", value: int(dec), sub: `of ${int(grow + dec)} comparable`, foot: `<span>${pct((dec / (grow + dec || 1)))} of comparable outlets</span>`, accent: "var(--bad)" })}
      ${kpi({ label: "New since comparison", value: int(fresh), sub: `No sales ${CMP[c]}`, foot: "<span>Not ranked</span>", accent: "var(--idle)" })}
      ${kpi({ label: "No sales this period", value: int(gone), sub: "Usually closed outlets", foot: "<span>Not ranked</span>", accent: "var(--idle)" })}
      </div>${t1}${t2}`;
  }

  // ------------------------------------------------------------------ category
  function pageCategory() {
    const r = rep(); if (!r) return noData();
    const cats = r.categories || {};
    if (!cats.sply && !cats.splm) return `<p class="empty">The report's category summary wasn't found. Check the Data quality page.</p>`;
    const tot = (k) => (cats[k] || []).find((x) => x.cat === "Total") || {};
    const block = (k, title, label) => {
      const rows = cats[k] || [];
      if (!rows.length) return "";
      return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p>${esc(label || "")}. Company-wide; outlet filters don't apply.</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">All stores sales</th><th class="num">All stores CP</th><th class="num">Own same-store sales</th><th class="num">Own same-store CP</th><th class="num">Franchise same-store sales</th><th class="num">Franchise same-store CP</th>${rows[0].this != null ? '<th class="num">Sales this period</th><th class="num">Sales comparison period</th>' : ""}</tr></thead><tbody>
        ${rows.map((c) => `<tr${c.cat === "Total" ? ' style="font-weight:650"' : ""}><td class="cell-primary">${esc(c.cat)}</td><td class="num">${delta(c.all)}</td><td class="num">${delta(c.all_cp)}</td><td class="num">${delta(c.own)}</td><td class="num">${delta(c.own_cp)}</td><td class="num">${delta(c.fran)}</td><td class="num">${delta(c.fran_cp)}</td>${c.this != null ? `<td class="num">${bdt(c.this)}</td><td class="num">${bdt(c.last)}</td>` : ""}</tr>`).join("")}
        </tbody></table></div></section>`;
    };
    const ty = tot("sply"), tm = tot("splm");
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      ${kpi({ label: "All stores vs last year", value: delta(ty.all), sub: "Sales growth", foot: `<span>CP ${delta(ty.all_cp)}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: "Own same-store vs last year", value: delta(ty.own), sub: "Sales growth", foot: `<span>CP ${delta(ty.own_cp)}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: "Franchise same-store vs last year", value: delta(ty.fran), sub: "Sales growth", foot: `<span>CP ${delta(ty.fran_cp)}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: "All stores vs last month", value: delta(tm.all), sub: "Sales growth", foot: `<span>CP ${delta(tm.all_cp)}</span>`, accent: "var(--series-3)" })}
      </div>
      ${block("sply", "Category growth vs last year", r.sply_label)}${block("splm", "Category growth vs last month", r.splm_label)}
      <p class="muted" style="margin:0">CP is contribution profit growth, as calculated in the report. "n/m" marks a category whose comparison base is too small to be meaningful.</p>`;
  }

  // ------------------------------------------------------------------ KPI performance
  function kpiAch(t, a, dir) {
    if (!isNum(t) || !isNum(a)) return null;
    let v;
    if (dir.startsWith("lower")) { if (a <= 0) return 1; v = t / a; } else { if (t === 0) return a >= 0 ? 1 : 0; v = a / t; }
    return Math.max(0, Math.min(1, v));
  }
  function kpiPeriods() {
    const ms = S.data.kpi?.months || [];
    if (!ms.length) return [];
    const [y, m] = ms[ms.length - 1].split("-").map(Number), fy = m >= 7 ? y : y - 1;
    const all = Array.from({ length: 12 }, (_, i) => { const mm = ((6 + i) % 12) + 1; return `${fy + (i >= 6 ? 1 : 0)}-${String(mm).padStart(2, "0")}`; });
    const has = new Set(ms), short = (k) => fmonth(k).slice(0, 3);
    const out = ms.filter((x) => all.includes(x)).map((x) => ({ k: x, label: fmonth(x), months: [x], len: 1 }));
    [["Q1", 0], ["Q2", 3], ["Q3", 6], ["Q4", 9]].forEach(([q, i]) => { const mm = all.slice(i, i + 3); if (mm.some((x) => has.has(x))) out.push({ k: q, label: `${q}, ${short(mm[0])} to ${short(mm[2])}`, months: mm, len: 3 }); });
    [["H1", 0], ["H2", 6]].forEach(([h, i]) => { const mm = all.slice(i, i + 6); if (mm.some((x) => has.has(x))) out.push({ k: h, label: `${h}, ${short(mm[0])} to ${short(mm[5])}`, months: mm, len: 6 }); });
    out.push({ k: "ytd", label: `Year to date, FY ${fy}–${String(fy + 1).slice(2)}`, months: all, len: 12 });
    out.forEach((p) => (p.have = p.months.filter((x) => has.has(x)).length));
    return out;
  }
  function kpiScores(rows, months) {
    const heads = new Map();
    for (const rec of rows) {
      const M = months.filter((m) => isNum(rec.a[m]));
      if (!M.length || !rec.w) continue;
      const sum = (v) => v.reduce((x, y) => x + y, 0);
      const pick = (v) => (rec.calc === "sum" ? sum(v) : sum(v) / v.length);
      const tv = M.map((m) => rec.t[m]).filter(isNum), av = M.map((m) => rec.a[m]);
      const t = tv.length ? pick(tv) : null, a = pick(av), ach = kpiAch(t, a, rec.dir);
      if (ach == null) continue;
      const h = heads.get(rec.head) || { head: rec.head, pts: 0, w: 0, cats: {}, metrics: [] };
      h.pts += ach * rec.w; h.w += rec.w;
      const cc = h.cats[rec.cat] || (h.cats[rec.cat] = { pts: 0, w: 0 });
      cc.pts += ach * rec.w; cc.w += rec.w;
      h.metrics.push({ cat: rec.cat, metric: rec.metric, w: rec.w, dir: rec.dir, calc: rec.calc, t, a, ach, pts: ach * rec.w, n: M.length });
      heads.set(rec.head, h);
    }
    const list = [...heads.values()].map((h) => ({ ...h, score: h.pts / h.w }));
    const nat = list.find((h) => h.head === "National");
    const rest = list.filter((h) => h.head !== "National").sort((x, y) => y.score - x.score);
    rest.forEach((h, i) => (h.rank = i + 1));
    return { nat, rest };
  }
  function zonalRl() {
    const m = {};
    (S.data.master?.outlets || []).forEach((o) => { if (o.zn && o.rl && !m[o.zn]) m[o.zn] = o.rl; });
    return m;
  }
  const catShort = (c) => { const l = c.toLowerCase(); return l.startsWith("business") ? "Business" : l.startsWith("satisf") ? "Customer" : l.startsWith("skill") ? "People" : l.startsWith("expense") ? "Expense" : c; };
  // Loose name key so "Mr. Ranjan" (KPI file) matches "Mr. Ranjon" (outlet master).
  const kname = (v) => String(v || "").toLowerCase().replace(/[^a-z]/g, "").replace(/[aeiou]/g, "");
  const KSHORT = [[/^sales \(in cr\)/i, "Sales"], [/^profit/i, "Profit"], [/sales growth/i, "SSG"], [/^expansion/i, "Expansion"], [/pakhaqs/i, "PAKHAQS"], [/store assess/i, "Store ass."],
    [/quality audit/i, "QA"], [/churn react/i, "Reactiv."], [/^churn/i, "Churn"], [/skill gap/i, "Skill gap"], [/consumable/i, "Consum."], [/stock loss/i, "Stock loss"], [/wastage/i, "Wastage"], [/salary/i, "Salary"]];
  const kShort = (m) => (KSHORT.find(([r]) => r.test(m)) || [0, m])[1];
  const KBANDS = ["91%-100%", "81%-90%", "71%-80%", "61%-70%", "60% or below"], KBANDS_S = ["91–100", "81–90", "71–80", "61–70", "60 or below"];
  const KBAND_CLS = ["b1", "b2", "b3", "b4", "b5"], KTXT = ["k-t1", "k-t2", "k-t3", "k-t4", "k-t5"];
  const kBand = (v) => (v >= 0.905 ? 0 : v >= 0.805 ? 1 : v >= 0.705 ? 2 : v >= 0.605 ? 3 : 4);
  const kCell = (v) => (!isNum(v) ? "" : v >= 0.905 ? "kc-g" : v >= 0.705 ? "kc-a" : "kc-r");
  const kLost = (h) => h.metrics.map((m) => ({ ...m, lost: m.w - m.pts })).sort((a, b) => b.lost - a.lost);
  // Average head: mean achievement on each KPI across the listed heads. The reference in the all-zonals view.
  function kpiAvg(heads, metrics, name) {
    if (!heads.length) return null;
    const ms = metrics.map((m) => {
      const got = heads.map((h) => h.metrics.find((x) => x.metric === m.metric)).filter(Boolean);
      if (!got.length) return null;
      const ach = got.reduce((a, x) => a + x.ach, 0) / got.length;
      const av = got.map((x) => x.a).filter(isNum);
      return { ...m, ach, pts: ach * m.w, t: null, a: null, aAvg: av.length ? av.reduce((a, v) => a + v, 0) / av.length : null, avg: true, n: got.length };
    }).filter(Boolean);
    const cats = {};
    ms.forEach((m) => { const c = cats[m.cat] || (cats[m.cat] = { pts: 0, w: 0 }); c.pts += m.pts; c.w += m.w; });
    return { head: name, avg: true, score: heads.reduce((a, h) => a + h.score, 0) / heads.length, cats, metrics: ms };
  }
  // What the KPI page shows: level, period, heads (RHO drill applied) and the reference head:
  // National on the RHO view, the RHO itself when drilled, and the zonal average on the zonal view (never National).
  function kpiView() {
    const K = S.data.kpi, periods = kpiPeriods(), P = periods.find((p) => p.k === S.kp) || periods.find((p) => p.k === "ytd");
    const rows = K[S.kl] || [], sc = kpiScores(rows, P.months), zr = zonalRl();
    const metrics = [...new Map(rows.map((r) => [r.metric, { metric: r.metric, cat: r.cat, w: r.w, dir: r.dir }])).values()];
    let heads = sc.rest, ref = sc.nat, refName = "National";
    if (S.kl === "zonal" && S.krho) {
      heads = heads.filter((h) => kname(zr[h.head]) === kname(S.krho));
      ref = kpiScores(K.rho || [], P.months).rest.find((h) => kname(h.head) === kname(S.krho)) || null;
      refName = S.krho;
    } else if (S.kl === "zonal") {
      refName = "All zonals";
      ref = kpiAvg(heads, metrics, refName);
    }
    return { K, P, periods, rows, heads, ref, refName, metrics, zr };
  }
  // Rank in the month before, for the movement arrows (single-month periods only).
  function kpiPrevRanks(V) {
    const ms = V.K.months || [], i = ms.indexOf(V.P.k);
    if (V.P.len !== 1 || i < 1) return null;
    return Object.fromEntries(kpiScores(V.rows, [ms[i - 1]]).rest.map((h) => [h.head, h.rank]));
  }
  const kMove = (prev, h) => {
    if (!prev || prev[h.head] == null) return "";
    const d = prev[h.head] - h.rank;
    return d > 0 ? `<span class="up k-mv" title="Up ${d} from last month">▲${d}</span>` : d < 0 ? `<span class="down k-mv" title="Down ${-d} from last month">▼${-d}</span>` : `<span class="k-mv muted">–</span>`;
  };
  const kBackBtns = () => (S.kl === "zonal" ? `<button type="button" class="btn" data-kback>← Back to RHOs</button>${S.krho ? `<button type="button" class="btn" data-kclear>All zonals</button>` : ""}` : "");
  function kpiScorecard(V, lvl) {
    const r = V.ref, cats = [...new Set(V.metrics.map((m) => m.cat))], bands = [0, 0, 0, 0, 0];
    V.heads.forEach((h) => bands[kBand(h.score)]++);
    const lost = r ? r.metrics.reduce((a, m) => a + m.w - m.pts, 0) : 0;
    return `<section class="panel k-sc"><div class="panel-head"><div><h2>${esc(V.refName)} scorecard</h2><p>${r?.avg ? `Average of ${int(V.heads.length)} ${lvl}. ` : ""}Category points against weight, and ${lvl} in each score band.</p></div></div>
      <div class="panel-body">
        <div class="k-sc-top"><div class="k-sc-val ${r ? KTXT[kBand(r.score)] : ""}">${r ? (r.score * 100).toFixed(1) : "—"}<small>/ 100</small></div>
          <div class="k-sc-meta"><span>${esc(V.P.label)} · ${r ? r.metrics.length : 0} KPIs</span><span>${lost.toFixed(1)} points lost</span></div></div>
        <div class="k-cats">${cats.map((c) => { const x = r?.cats[c], v = x ? x.pts / x.w : null; return `<div class="k-cat"><span>${esc(catShort(c))}</span><div class="k-track"><i class="${isNum(v) ? KBAND_CLS[kBand(v)] : ""}" style="width:${isNum(v) ? v * 100 : 0}%"></i></div><b>${x ? `${x.pts.toFixed(1)} of ${int(x.w)}` : "—"}</b></div>`; }).join("")}</div>
        <div class="av-stack">${bands.map((v, i) => (v ? `<i class="${KBAND_CLS[i]}" style="flex-grow:${v}" title="${KBANDS[i]}: ${v}"></i>` : "")).join("")}</div>
        <ul class="k-bands">${KBANDS_S.map((t, i) => `<li${bands[i] ? ` data-kband="${i}" tabindex="0" role="button" title="${lvl} scoring ${KBANDS[i]}"` : ' class="zero"'}><i class="${KBAND_CLS[i]}"></i><span>${t}</span><b>${int(bands[i])}</b></li>`).join("")}</ul>
      </div></section>`;
  }
  // KPI cards, biggest points loss first, four visible at a time in a scroll box.
  function kpiCards(V, lvl) {
    const r = V.ref;
    const list = V.metrics.map((m) => {
      const got = V.heads.map((h) => ({ h, x: h.metrics.find((y) => y.metric === m.metric) })).filter((g) => g.x);
      const rm = r?.metrics.find((y) => y.metric === m.metric);
      return { m, got, rm, lost: rm ? m.w - rm.pts : 0 };
    }).sort((a, b) => b.lost - a.lost);
    const cards = list.map(({ m, got, rm }) => {
      const hit = got.filter((g) => g.x.ach >= 0.999).length, worst = got.slice().sort((a, b) => a.x.ach - b.x.ach)[0], v = rm?.ach, b = isNum(v) ? kBand(v) : null;
      const note = !rm ? "" : rm.avg ? `average of ${int(rm.n)} ${lvl}` : `${kfmt(m.metric, rm.a)} vs ${kfmt(m.metric, rm.t)}`;
      return `<article class="k-kc" data-kmetric="${esc(m.metric)}" tabindex="0" role="button" title="Rank every head on ${esc(m.metric)}">
        <div class="k-kc-h"><b>${esc(m.metric)}</b><span>${esc(catShort(m.cat))} · weight ${int(m.w)}${m.dir.startsWith("lower") ? " · lower is better" : ""}</span></div>
        <div class="k-kc-v"><strong class="${b == null ? "" : KTXT[b]}">${pct(v, 0)}</strong><span>${note}</span></div>
        <div class="k-track"><i class="${b == null ? "" : KBAND_CLS[b]}" style="width:${isNum(v) ? v * 100 : 0}%"></i></div>
        <div class="k-kc-f"><span>${hit} of ${got.length} hit target</span>${worst && worst.x.ach < 0.999 ? `<span>Low: ${esc(worst.h.head)} ${pct(worst.x.ach, 0)}</span>` : ""}</div></article>`;
    }).join("");
    return `<section class="panel k-kcp"><div class="panel-head"><div><h2>KPI cards</h2><p>${esc(V.refName)} on each KPI, biggest points loss first. Click a card to rank every head on it.</p></div><div class="panel-tools"><span class="k-kcn" data-kcn>1–4 of ${list.length}</span><button type="button" class="btn k-arrow" data-kscroll="-1" aria-label="Previous KPIs">↑</button><button type="button" class="btn k-arrow" data-kscroll="1" aria-label="Next KPIs">↓</button></div></div>
      <div class="panel-body"><div class="k-kcs" data-kcs="${list.length}">${cards}</div></div></section>`;
  }
  function kpiMatrix(V, lvl, prev) {
    const ms = V.metrics, rho = S.kl === "rho";
    const cell = (h, m) => h.metrics.find((x) => x.metric === m.metric);
    const unit = (m) => (/\(in cr\)/i.test(m.metric) ? "Cr" : /%|growth|churn|skill|assessment|audit/i.test(m.metric) ? "%" : "");
    const num = (m, v) => (!isNum(v) ? "—" : unit(m) === "Cr" ? v.toFixed(2) : unit(m) === "%" ? (v * 100).toFixed(Math.abs(v) < 0.1 ? 2 : 1) + "%" : Number.isInteger(v) ? String(v) : v.toFixed(2));
    const td = (c, m) => {
      const v = c?.avg ? c.aAvg : c?.a;
      const tip = !c ? "" : c.avg ? `average actual of ${c.n} · ${pct(c.ach, 1)} average achievement` : `actual ${kfmt(m.metric, c.a)} · target ${kfmt(m.metric, c.t)} · ${pct(c.ach, 1)} achieved`;
      return `<td class="${kCell(c?.ach)}" title="${esc(m.metric)}: ${tip}">${num(m, v)}</td>`;
    };
    const raw = (m, v) => (!isNum(v) ? "" : unit(m) === "%" ? (v * 100).toFixed(4) : String(v));
    NCSV.kmatrix = () => [`kpi_matrix_${S.kl}_${V.P.k}`, [rho ? "RHO" : "Zonal", "Rank", "Score %", ...ms.flatMap((m) => [`${m.metric} actual${unit(m) ? ` (${unit(m)})` : ""}`, `${m.metric} target${unit(m) ? ` (${unit(m)})` : ""}`, `${m.metric} achievement %`])],
      V.heads.map((h) => [h.head, h.rank, pcsv(h.score), ...ms.flatMap((m) => { const c = cell(h, m); return [raw(m, c?.a), raw(m, c?.t), pcsv(c?.ach)]; })]), V.P.k];
    const refRow = V.ref ? `<tr class="k-ref"><td>${esc(V.refName)}${V.ref.avg ? ' <small class="cell-secondary">average</small>' : ""}</td><td></td><td class="num"><strong>${pct(V.ref.score, 1)}</strong></td>${ms.map((m) => td(cell(V.ref, m), m)).join("")}</tr>` : "";
    return `<section class="panel k-mat"><div class="panel-head"><div><h2>KPI heat-matrix, ${esc(V.P.label)}${S.krho ? ` · ${esc(S.krho)}` : ""}</h2><p>Achieved number on every KPI, coloured by achievement against each head's own target: green 91%+, amber 71–90%, red 70% or below. Hover a cell for its target. ${rho ? "Click a row for that RHO's zonals, " : ""}click a name for the KPI breakdown, or a KPI heading to rank everyone on it.</p></div><div class="panel-tools">${kBackBtns()}${csvBtn("kmatrix")}</div></div>
      <div class="table-wrap" style="max-height:640px"><table><thead><tr><th>${rho ? "RHO" : "Zonal"}</th><th class="num">Rank</th><th class="num">Score</th>${ms.map((m) => `<th class="k-mh" data-kmetric="${esc(m.metric)}" tabindex="0" title="${esc(m.metric)} · weight ${int(m.w)}${m.dir.startsWith("lower") ? " · lower is better" : ""}">${esc(kShort(m.metric))}<small>${unit(m) === "Cr" ? "Cr · " : ""}w${int(m.w)}</small></th>`).join("")}</tr></thead><tbody>
      ${refRow}${V.heads.map((h) => `<tr${rho ? ` data-kdrill="${esc(h.head)}" tabindex="0" class="k-click"` : ""}><td><span class="k-name" data-khead="${esc(h.head)}" tabindex="0" role="button">${esc(h.head)}</span>${rho ? "" : `<small class="cell-secondary">RHO ${esc(V.zr[h.head] || "—")}</small>`}</td><td class="num">${int(h.rank)} ${kMove(prev, h)}</td><td class="num"><strong>${pct(h.score, 1)}</strong></td>${ms.map((m) => td(cell(h, m), m)).join("")}</tr>`).join("")}
      </tbody></table></div></section>`;
  }
  function kpiTrend(V) {
    const ms = V.K.months || [];
    if (ms.length < 2) return `<section class="panel"><div class="panel-head"><div><h2>Month on month</h2><p>Rank arrows and score trend lines appear here once a second month's KPI file is uploaded. Only ${esc(ms.map(fmonth).join(", ") || "no month")} so far.</p></div></div></section>`;
    const per = ms.map((m) => Object.fromEntries(kpiScores(V.rows, [m]).rest.map((h) => [h.head, h])));
    const W = 120, H = 26, spark = (vals) => { const pts = vals.map((v, i) => (isNum(v) ? `${((i / (vals.length - 1)) * W).toFixed(1)},${(H - 3 - v * (H - 6)).toFixed(1)}` : null)).filter(Boolean); return `<svg class="k-spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts.join(" ")}"/></svg>`; };
    const rowsT = V.heads.map((h) => { const sc = per.map((p) => p[h.head]?.score), rk = per.map((p) => p[h.head]?.rank); const f = rk.find(isNum), l = rk[rk.length - 1]; return { h, sc, rk, d: isNum(f) && isNum(l) ? f - l : null }; });
    NCSV.ktrend = () => [`kpi_trend_${S.kl}`, ["Head", ...ms.map((m) => fmonth(m) + " score %"), ...ms.map((m) => fmonth(m) + " rank")], rowsT.map((r) => [r.h.head, ...r.sc.map(pcsv), ...r.rk.map((v) => v ?? "")]), ms[ms.length - 1]];
    return `<section class="panel"><div class="panel-head"><div><h2>Month on month</h2><p>Monthly score and rank for each head, ${esc(fmonth(ms[0]))} to ${esc(fmonth(ms[ms.length - 1]))}. The arrow is the rank change over that span.</p></div><div class="panel-tools">${csvBtn("ktrend")}</div></div>
      <div class="table-wrap" style="max-height:560px"><table><thead><tr><th>Head</th>${ms.map((m) => `<th class="num">${esc(fmonth(m))}</th>`).join("")}<th class="num">Rank change</th><th>Trend</th></tr></thead><tbody>
      ${rowsT.map((r) => `<tr data-khead="${esc(r.h.head)}" tabindex="0" class="k-click"><td>${esc(r.h.head)}</td>${r.sc.map((v, i) => `<td class="num">${pct(v, 1)}<span class="cell-secondary">${r.rk[i] ? "Rank " + r.rk[i] : ""}</span></td>`).join("")}<td class="num">${r.d == null ? "—" : r.d > 0 ? `<span class="up">▲${r.d}</span>` : r.d < 0 ? `<span class="down">▼${-r.d}</span>` : "–"}</td><td class="${r.d < 0 ? "k-dn" : "k-upl"}">${spark(r.sc)}</td></tr>`).join("")}
      </tbody></table></div></section>`;
  }
  // Points lost view: any head's lost points, where every head loses points, and a head × KPI table of points lost.
  function kpiLostView(V, lvl, tools, prev) {
    const one = S.kl === "rho" ? "RHO" : "zonal";
    const sel = (S.klh && V.heads.find((h) => h.head === S.klh)) || V.ref || V.heads[0];
    if (!sel) return `<p class="empty">No KPI scores for this selection.</p>`;
    const selName = sel.avg ? `${sel.head} (average)` : sel.head;
    const opts = [...(V.ref ? [["", V.ref.avg ? `${V.refName} (average)` : V.refName]] : []), ...V.heads.map((h) => [h.head, `${h.rank}. ${h.head}`])];
    const picker = `<select class="sel" data-sel="klh" aria-label="Show points lost for">${opts.map(([v, t]) => `<option value="${esc(v)}" ${(sel === V.ref ? "" : sel.head) === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    const lost = kLost(sel), tot = lost.reduce((a, m) => a + m.lost, 0), max = Math.max(...lost.map((m) => m.lost), 0.0001);
    const near = sel.metrics.filter((m) => m.ach < 0.999).sort((a, b) => b.ach - a.ach).slice(0, 4);
    const now = (m) => (isNum(m.t) && isNum(m.a) ? `Now ${kfmt(m.metric, m.a)}, target ${kfmt(m.metric, m.t)}` : `${pct(m.ach, 1)} achieved on average`);
    NCSV.klost = () => [`kpi_points_lost_${kname(sel.head) || "head"}_${V.P.k}`, ["KPI", "Category", "Weight", "Target", "Actual", "Achievement %", "Points earned", "Points lost"], lost.map((m) => [m.metric, catShort(m.cat), m.w, m.t ?? "", m.a ?? "", pcsv(m.ach), m.pts.toFixed(2), m.lost.toFixed(2)]), V.P.k];
    const headPanel = `<section class="panel k-lh"><div class="panel-head"><div><h2>Where ${esc(selName)} loses points</h2><p>Weight minus points earned on each KPI, biggest loss first. Pick anyone from the list or click a row in the table below.</p></div><div class="panel-tools">${picker}${csvBtn("klost")}</div></div>
      <div class="panel-body"><div class="k-facts"><span>Score <b class="${KTXT[kBand(sel.score)]}">${(sel.score * 100).toFixed(1)}</b></span><span>Points lost <b class="down">${tot.toFixed(1)}</b></span>${sel.rank ? `<span>Rank <b>${sel.rank} of ${V.heads.length}</b></span>` : ""}</div>
        <div class="k-lost">${lost.map((m) => `<div class="k-lrow" data-kmetric="${esc(m.metric)}" tabindex="0" role="button"><span><strong>${esc(m.metric)}</strong><small>${esc(catShort(m.cat))} · ${pct(m.ach, 1)} achieved · weight ${int(m.w)}</small></span><div class="k-track"><i class="${m.ach >= 0.9 ? "b2" : m.ach >= 0.7 ? "b3" : "b5"}" style="width:${(m.lost / max) * 100}%"></i></div><b>${m.lost < 0.005 ? "0" : "−" + m.lost.toFixed(2)}</b></div>`).join("")}</div>
        ${near.length ? `<div class="k-near-h">Closest to target: the easiest points to win back</div><ul class="k-near">${near.map((m) => `<li data-kmetric="${esc(m.metric)}" tabindex="0" role="button"><span><strong>${esc(m.metric)}</strong><small>${now(m)} · ${pct(m.ach, 1)} achieved</small></span><b class="up">+${(m.w - m.pts).toFixed(2)} pts</b></li>`).join("")}</ul>` : ""}
      </div></section>`;
    const net = V.metrics.map((m) => {
      const got = V.heads.map((h) => h.metrics.find((x) => x.metric === m.metric)).filter(Boolean);
      return { m, avg: got.length ? got.reduce((a, x) => a + x.w - x.pts, 0) / got.length : 0, miss: got.filter((x) => x.ach < 0.999).length, n: got.length };
    }).sort((a, b) => b.avg - a.avg);
    const nmax = Math.max(...net.map((x) => x.avg), 0.0001);
    NCSV.klostnet = () => [`kpi_points_lost_by_kpi_${S.kl}_${V.P.k}`, ["KPI", "Category", "Weight", `Average points lost per ${one}`, `${lvl} below target`, lvl], net.map((x) => [x.m.metric, catShort(x.m.cat), x.m.w, x.avg.toFixed(2), x.miss, x.n]), V.P.k];
    const netPanel = `<section class="panel"><div class="panel-head"><div><h2>Where every ${one} loses points</h2><p>Average points lost per ${one} on each KPI${S.krho ? ` under ${esc(S.krho)}` : ""}, and how many of the ${int(V.heads.length)} ${lvl} are below target. Click a KPI to rank everyone on it.</p></div><div class="panel-tools">${csvBtn("klostnet")}</div></div>
      <div class="panel-body"><div class="k-lost">${net.map((x) => `<div class="k-lrow" data-kmetric="${esc(x.m.metric)}" tabindex="0" role="button"><span><strong>${esc(x.m.metric)}</strong><small>${x.miss} of ${x.n} below target · weight ${int(x.m.w)}</small></span><div class="k-track"><i class="${x.avg / x.m.w <= 0.1 ? "b2" : x.avg / x.m.w <= 0.3 ? "b3" : "b5"}" style="width:${(x.avg / nmax) * 100}%"></i></div><b>${x.avg < 0.005 ? "0" : "−" + x.avg.toFixed(2)}</b></div>`).join("")}</div></div></section>`;
    const ms = V.metrics;
    const rowsL = V.heads.map((h) => {
      const l = kLost(h), x = { key: h.head, head: h.head, name: h.head, sub: S.kl === "zonal" ? `RHO ${V.zr[h.head] || "not in outlet master"}` : "", rank: h.rank, score: h.score, lost: h.w - h.pts, leak: l[0] };
      ms.forEach((m, i) => { const c = h.metrics.find((y) => y.metric === m.metric); x[`m${i}`] = c ? c.w - c.pts : null; x[`a${i}`] = c?.ach; });
      return x;
    });
    const table = mountTable("kpilost-" + S.kl, {
      title: `Points lost by ${one} and KPI, ${V.P.label}`, file: `kpi_points_lost_${S.kl}_${V.P.k}`, pageSize: 70, tools,
      desc: (n) => `${n} ${lvl}. Points lost on each KPI (weight minus points earned), coloured by achievement. Click a row to show it above, a name for the full breakdown, or a heading to sort.`,
      rows: rowsL, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "lost", rowAttr: (x) => `data-klh="${esc(x.head)}" tabindex="0" class="k-click${x.head === sel.head ? " k-sel" : ""}"`,
      cols: [{ k: "rank", label: "Rank", num: 1, fmt: (x) => `${int(x.rank)} ${kMove(prev, x)}`, csv: (x) => x.rank, val: (x) => -x.rank },
        { k: "name", label: S.kl === "rho" ? "RHO" : "Zonal", fmt: (x) => `<span class="cell-primary k-name" data-khead="${esc(x.head)}" tabindex="0" role="button">${esc(x.name)}</span>${x.sub ? `<span class="cell-secondary">${esc(x.sub)}</span>` : ""}`, csv: (x) => x.name, val: (x) => x.name },
        { k: "score", label: "Score", num: 1, fmt: (x) => `<strong>${pct(x.score, 1)}</strong>`, csv: (x) => pcsv(x.score) },
        { k: "lost", label: "Points lost", num: 1, fmt: (x) => `<strong class="down">−${x.lost.toFixed(1)}</strong>`, csv: (x) => x.lost.toFixed(2) },
        { k: "leak", label: "Biggest loss", fmt: (x) => (x.leak ? `<span class="cell-primary">${esc(kShort(x.leak.metric))}</span><span class="cell-secondary">−${x.leak.lost.toFixed(2)} pts</span>` : "—"), csv: (x) => x.leak?.metric || "", val: (x) => x.leak?.lost },
        ...ms.map((m, i) => ({ k: `m${i}`, label: kShort(m.metric), csvLabel: m.metric + " points lost", num: 1, fmt: (x) => (x[`m${i}`] == null ? "—" : `<span class="k-lc ${x[`m${i}`] < 0.005 ? "" : kCell(x[`a${i}`])}">${x[`m${i}`] < 0.005 ? "0" : x[`m${i}`].toFixed(1)}</span>`), csv: (x) => (x[`m${i}`] == null ? "" : x[`m${i}`].toFixed(2)) }))],
    });
    return `<div class="k-two">${headPanel}${netPanel}</div>${table}`;
  }
  // Drawer: every head ranked on one KPI.
  function openKpiMetric(metric) {
    const V = kpiView();
    const list = V.heads.map((h) => ({ h, x: h.metrics.find((y) => y.metric === metric) })).filter((g) => g.x).sort((a, b) => b.x.ach - a.x.ach || a.h.rank - b.h.rank);
    const r = V.ref?.metrics.find((y) => y.metric === metric), m = V.metrics.find((y) => y.metric === metric) || {};
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = `${metric}, ${V.P.label}`;
    $("#drawerBody").innerHTML = `<div class="stat-grid three"><div class="stat"><small>${esc(V.refName)}${r?.avg ? " (average)" : ""}</small><strong>${pct(r?.ach, 1)}</strong><div style="font-size:12px">${r?.avg ? `average of ${int(r.n)}` : `${kfmt(metric, r?.a)} vs ${kfmt(metric, r?.t)}`}</div></div>
        <div class="stat"><small>Hit target</small><strong>${list.filter((g) => g.x.ach >= 0.999).length} of ${list.length}</strong></div><div class="stat"><small>Weight</small><strong>${int(m.w)}</strong><div style="font-size:12px">${m.dir?.startsWith("lower") ? "Lower is better" : "Higher is better"}</div></div></div>
      <div class="table-wrap" style="max-height:560px"><table class="compact"><thead><tr><th>#</th><th>Head</th><th class="num">Target</th><th class="num">Actual</th><th class="num">Achievement</th><th class="num">Points</th></tr></thead><tbody>
      ${list.map((g, i) => `<tr data-khead="${esc(g.h.head)}" tabindex="0" class="k-click"><td>${i + 1}</td><td>${esc(g.h.head)}</td><td class="num">${kfmt(metric, g.x.t)}</td><td class="num">${kfmt(metric, g.x.a)}</td><td class="num ${kCell(g.x.ach)}">${pct(g.x.ach, 1)}</td><td class="num">${g.x.pts.toFixed(2)} / ${int(g.x.w)}</td></tr>`).join("")}</tbody></table></div>`;
    wireDyn($("#drawerBody"));
    showDrawer();
  }
  function openKpiBand(band) {
    const V = kpiView(), list = V.heads.filter((h) => kBand(h.score) === band);
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = `Scores ${KBANDS[band]}, ${V.P.label}`;
    $("#drawerBody").innerHTML = `<div class="table-wrap" style="max-height:none"><table class="compact"><thead><tr><th>Rank</th><th>Head</th><th class="num">Score</th></tr></thead><tbody>
      ${list.map((h) => `<tr data-khead="${esc(h.head)}" tabindex="0" class="k-click"><td>${h.rank}</td><td>${esc(h.head)}</td><td class="num"><strong>${pct(h.score, 1)}</strong></td></tr>`).join("")}</tbody></table></div>`;
    wireDyn($("#drawerBody"));
    showDrawer();
  }
  function pageKPI() {
    const K = S.data.kpi, periods = kpiPeriods();
    if (!periods.length) return `<p class="empty">No KPI performance file is loaded yet. Add one to the Performance folder.</p>`;
    if (!periods.find((p) => p.k === S.kp)) S.kp = periods.filter((p) => p.len === 1).slice(-1)[0].k;
    if (S.kl !== "zonal" || !S.krho) S.krho = null;
    const V = kpiView(), P = V.P, rows = V.rows, ref = V.ref, rest = V.heads;
    const cats = [...new Set(rows.map((x) => x.cat))];
    const zr = V.zr, lvlName = S.kl === "rho" ? "RHO" : "Zonal", lvlP = S.kl === "rho" ? "RHOs" : "zonals", one = S.kl === "rho" ? "RHO" : "zonal";
    const periodSel = `<select class="sel" data-sel="kp" aria-label="Period">${periods.map((p) => `<option value="${p.k}" ${p.k === S.kp ? "selected" : ""}>${esc(p.label)}${p.len > 1 && p.have < p.len ? ` (${p.have} of ${p.len} months)` : ""}</option>`).join("")}</select>`;
    const rhoNames = [...new Set((K.rho || []).map((r) => r.head))].filter((h) => h !== "National").sort();
    const rhoSel = S.kl === "zonal" ? `<select class="sel" data-sel="krho" aria-label="RHO">${[["", "All RHOs"], ...rhoNames.map((h) => [h, h])].map(([v, t]) => `<option value="${esc(v)}" ${(S.krho || "") === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>` : "";
    const lvlSeg = seg("kl", [["rho", "RHO"], ["zonal", "Zonal"]], "Level");
    const tools = `${lvlSeg}${seg("kv", [["rank", "Ranking"], ["summary", "Summary"], ["lost", "Points lost"]], "View")}${S.kv !== "summary" ? periodSel : ""}${rhoSel}`;
    const tableTools = `${lvlSeg}${rhoSel}`;
    const partial = P.len > 1 && P.have < P.len ? `<p class="note">${esc(P.label)} is partial: ${P.have} of ${P.len} months uploaded. Scores cover the uploaded months only.</p>` : "";
    const sub = (h) => (S.kl === "zonal" ? `RHO ${zr[h.head] || "not in outlet master"}` : `${h.metrics.length} KPIs`);
    const prev = kpiPrevRanks(V);
    let body;
    if (S.kv === "lost") {
      body = kpiLostView(V, lvlP, tableTools, prev);
    } else if (S.kv === "summary") {
      const cols = periods.filter((p) => p.have);
      const keep = (h) => !S.krho || kname(zr[h.head]) === kname(S.krho);
      const byP = Object.fromEntries(cols.map((p) => [p.k, kpiScores(rows, p.months).rest.filter(keep)]));
      const heads = [...new Set(Object.values(byP).flat().map((h) => h.head))];
      const data = heads.map((h) => { const x = { key: h, name: h, head: h }; cols.forEach((p) => { const f = byP[p.k].find((y) => y.head === h); x[p.k] = f?.score ?? null; x[p.k + "_r"] = f?.rank; }); x.sub = S.kl === "zonal" ? `RHO ${zr[h] || "not in outlet master"}` : ""; return x; });
      body = mountTable("kpisum-" + S.kl, {
        title: `${lvlName} summary across periods${S.krho ? ` · ${S.krho}` : ""}`, file: `kpi_summary_${S.kl}`, pageSize: 70, tools: tableTools,
        desc: (n) => `${n} ${lvlP}. Scores with rank underneath. Partial quarters and halves cover uploaded months only.`,
        rows: data, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "ytd", rowAttr: (x) => `data-khead="${esc(x.head)}" tabindex="0" class="k-click"`,
        cols: [{ k: "name", label: lvlName, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span>${x.sub ? `<span class="cell-secondary">${esc(x.sub)}</span>` : ""}`, csv: (x) => x.name, val: (x) => x.name },
          ...cols.map((p) => ({ k: p.k, label: p.len === 12 ? "Year to date" : p.len === 1 ? p.label : p.k, num: 1, fmt: (x) => (isNum(x[p.k]) ? `<span class="k-pill ${kCell(x[p.k])}">${pct(x[p.k], 1)}</span><span class="cell-secondary">${x[p.k + "_r"] ? "Rank " + x[p.k + "_r"] : ""}</span>` : "—"), csv: (x) => pcsv(x[p.k]) }))],
      });
    } else {
      const table = mountTable("kpi-" + S.kl, {
        title: `${lvlName} ranking, ${P.label}${S.krho ? ` · ${S.krho}` : ""}`, file: `kpi_${S.kl}_${P.k}`, pageSize: 70, tools: tableTools,
        desc: (n) => `${n} ${lvlP}. Score = weighted achievement across all KPIs, each KPI capped at 100%. Category cells show achievement and points of weight. Click a row for the KPI breakdown.`,
        rows: rest.map((h) => { const l = kLost(h); return { ...h, key: h.head, name: h.head, sub: sub(h), leak: l[0], ...Object.fromEntries(cats.map((c, i) => [`c${i}`, h.cats[c] ? h.cats[c].pts / h.cats[c].w : null])) }; }),
        key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "score", rowAttr: (x) => `data-khead="${esc(x.head)}" tabindex="0" class="k-click"`,
        cols: [{ k: "rank", label: "Rank", num: 1, fmt: (x) => `<span class="k-rk${x.rank <= 3 ? " top" : ""}">${int(x.rank)}</span>${kMove(prev, x)}`, csv: (x) => x.rank, val: (x) => -x.rank },
          { k: "name", label: lvlName, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name, val: (x) => x.name },
          { k: "score", label: "Score", num: 1, fmt: (x) => `<div class="k-scc"><strong class="${KTXT[kBand(x.score)]}">${pct(x.score, 1)}</strong><span class="k-track"><i class="${KBAND_CLS[kBand(x.score)]}" style="width:${x.score * 100}%"></i></span></div>`, csv: (x) => pcsv(x.score) },
          ...cats.map((c, i) => ({ k: `c${i}`, label: catShort(c), num: 1, fmt: (x) => (x.cats[c] ? `<span class="k-pill ${kCell(x[`c${i}`])}">${pct(x[`c${i}`], 1)}</span><span class="cell-secondary">${x.cats[c].pts.toFixed(1)} of ${int(x.cats[c].w)}</span>` : "—"), csv: (x) => pcsv(x[`c${i}`]) })),
          { k: "leak", label: "Biggest loss", fmt: (x) => (x.leak ? `<span class="cell-primary">${esc(kShort(x.leak.metric))}</span><span class="cell-secondary">−${x.leak.lost.toFixed(2)} pts</span>` : "—"), csv: (x) => x.leak?.metric || "", val: (x) => x.leak?.lost }],
      });
      body = `<div class="k-two">${kpiScorecard(V, lvlP)}${kpiCards(V, lvlP)}</div>${table}${kpiMatrix(V, lvlP, prev)}${kpiTrend(V)}`;
    }
    if (S.kfocus) { const f = S.kfocus; S.kfocus = null; AFTER.push(() => $(f)?.scrollIntoView({ block: "start" })); }
    AFTER.push(() => { const t = $(".topbar"); if (t) document.documentElement.style.setProperty("--k-top", t.offsetHeight + "px"); });
    const top = rest[0], low = rest[rest.length - 1];
    const drill = S.krho ? `<div class="k-drill"><span>Zonals under <strong>${esc(S.krho)}</strong>. Ranks are network-wide.</span><span class="k-drill-b">${kBackBtns()}</span></div>` : "";
    const bar = `<div class="panel k-bar"><span class="k-bar-l">${lvlName} view · ${S.kv === "summary" ? "all periods" : esc(P.label)}</span><div class="panel-tools">${tools}</div></div>`;
    const who = (h) => (h ? `<span class="k-kname" title="${esc(h.head)}">${esc(h.head)}</span>` : "—");
    const refLabel = ref?.avg ? "Average zonal score" : `${esc(V.refName)} score`;
    return `${bar}${drill}<div class="kpis k-kpis">
      ${kpi({ label: `${refLabel}, ${P.label}`, value: pct(ref?.score), sub: ref ? `<span class="k-pill ${kCell(ref.score)}">${KBANDS[kBand(ref.score)]}</span>` : "", foot: `<span>${ref ? (ref.avg ? `${int(rest.length)} zonals averaged` : `${ref.metrics.length} KPIs`) : `${esc(V.refName)} is not in the file`}</span><span>${P.have} month${P.have === 1 ? "" : "s"} of data</span>`, accent: "var(--info)" })}
      ${kpi({ label: `Top ${one}`, value: who(top), sub: top ? `<span class="k-pill ${kCell(top.score)}">${pct(top.score, 1)}</span>` : "", foot: `<span>Rank ${top?.rank ?? "—"}${S.krho ? " network-wide" : ` of ${rest.length}`}</span>`, accent: "var(--good)" })}
      ${kpi({ label: `Lowest ${one}`, value: who(low), sub: low ? `<span class="k-pill ${kCell(low.score)}">${pct(low.score, 1)}</span>` : "", foot: `<span>Rank ${low?.rank ?? "—"}${S.krho ? " network-wide" : ` of ${rest.length}`}</span>`, accent: "var(--bad)" })}
      ${kpi({ label: "Performance files", value: int(K.files.length), sub: `Months: ${K.months.map(fmonth).join(", ")}`, foot: "<span>Newest file wins for each month</span>", accent: "var(--idle)" })}
      </div>${partial}${body}`;
  }
  function kfmt(metric, v) {
    if (!isNum(v)) return "—";
    if (/\(in cr\)/i.test(metric)) return v.toFixed(2) + " Cr";
    if (/%|growth|churn|skill|assessment|audit/i.test(metric)) return pct(v, Math.abs(v) < 0.01 ? 3 : 2);
    return Number.isInteger(v) ? String(v) : v.toFixed(2);
  }
  function openHead(head) {
    const periods = kpiPeriods(), P = periods.find((p) => p.k === S.kp) || periods.find((p) => p.k === "ytd");
    const all = kpiScores(S.data.kpi[S.kl] || [], P.months), h = all.rest.find((x) => x.head === head);
    if (!h) return;
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = `${head}, ${P.label}`;
    const cats = [...new Set(h.metrics.map((m) => m.cat))];
    $("#drawerBody").innerHTML = `
      <div class="stat-grid">
        <div class="stat"><small>Score</small><strong>${pct(h.score)}</strong><div style="font-size:12px">Rank ${h.rank} of ${all.rest.length}</div></div>
        ${cats.map((c) => `<div class="stat"><small>${esc(catShort(c))}</small><strong>${pct(h.cats[c].pts / h.cats[c].w)}</strong><div style="font-size:12px">${h.cats[c].pts.toFixed(1)} of ${h.cats[c].w} points</div></div>`).join("")}
      </div>
      <div class="table-wrap" style="max-height:none"><table><thead><tr><th>KPI</th><th class="num">Weight</th><th class="num">Target</th><th class="num">Actual</th><th class="num">Achievement</th><th class="num">Points</th></tr></thead><tbody>
      ${h.metrics.map((m) => `<tr><td><span class="cell-primary">${esc(m.metric)}</span><span class="cell-secondary">${esc(catShort(m.cat))}${m.dir.startsWith("lower") ? ", lower is better" : ""}${P.len > 1 ? `, ${m.calc === "sum" ? "summed" : "averaged"} over ${m.n} month${m.n === 1 ? "" : "s"}` : ""}</span></td><td class="num">${int(m.w)}</td><td class="num">${kfmt(m.metric, m.t)}</td><td class="num">${kfmt(m.metric, m.a)}</td><td class="num">${pct(m.ach)}</td><td class="num">${m.pts.toFixed(2)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted" style="margin:0;font-size:12px">Targets and actuals are the scoring values from the KPI file. Achievement is capped at 100%. Sum and average rules come from each KPI's calc type in the file.</p>`;
    showDrawer();
  }

  // ------------------------------------------------------------------ loss-making outlets (outlet P&L)
  const AGE_BANDS = [["Under 6 months", 0, 6], ["6 to 12 months", 6, 12], ["1 to 2 years", 12, 24], ["2 years or more", 24, Infinity]];
  const LOSS_STATUS = {
    new: { label: "New loss", cls: "bad" }, wide: { label: "Loss widening", cls: "bad" },
    narrow: { label: "Loss narrowing", cls: "warn" }, first: { label: "No prior month", cls: "idle" }, ytd: { label: "Loss year to date", cls: "bad" },
  };
  function pnlCalc(o) {
    const after = S.pbasis === "after";
    const ytd = S.pm === "ytd";
    const pl = after ? o.p : o.g, pl0 = ytd ? null : after ? o.p0 : o.g0;
    const fixed = (o.ox || 0) + (after ? o.ofc || 0 : 0);
    const rate = o.s > 0 ? ((o.gp || 0) + (o.oi || 0)) / o.s : null;
    const be = rate > 0 ? fixed / rate : null;
    const P = S.data.pnl, [y, m] = (ytd ? P.months[P.months.length - 1] : S.pm).split("-").map(Number);
    const ld = o.ld || o.m?.ld;
    let age = null;
    if (ld) { const [ly, lm] = ld.split("-").map(Number); age = (y - ly) * 12 + (m - lm); }
    let st = null;
    const closed = !(o.s >= 1);
    if (!closed && isNum(pl) && pl < 0) st = ytd ? "ytd" : !isNum(pl0) ? "first" : pl0 >= 0 ? "new" : pl < pl0 ? "wide" : "narrow";
    return {
      pl, pl0, chg: isNum(pl) && isNum(pl0) ? pl - pl0 : null, gpp: ratio(o.gp, o.s), oxp: ratio(o.ox, o.s),
      be, need: isNum(be) && o.s > 0 ? be / o.s - 1 : null, age, st, closed, loss: !closed && isNum(pl) && pl < 0,
    };
  }
  const ageBand = (a) => (a == null ? "Opening date unknown" : AGE_BANDS.find(([, lo, hi]) => a >= lo && a < hi)[0]);
  const ageTxt = (a) => (a == null ? "—" : a < 12 ? `${a} mo` : `${(a / 12).toFixed(1)} yr`);
  function ageDrillLink(bandName, scope, value, label, cls = "") {
    return `<button type="button" class="age-drill-link ${cls}" data-age-band="${esc(bandName)}" data-age-scope="${scope}" aria-label="${esc(label + ": " + bandName)}" title="${esc(label + ": " + bandName)}">${value}</button>`;
  }
  function openAgeOutlets(bandName, onlyLoss) {
    if (!S.data.pnl) return;
    S.lastFocus = document.activeElement;
    S.ageDrill = { bandName, onlyLoss, outlet: null };
    delete S.tables["age-outlets"];
    drawAgeOutlets();
  }
  function drawAgeOutlets() {
    const context = S.ageDrill;
    if (!context) return;
    const { bandName, onlyLoss } = context;
    const rows = inView().map((o) => ({ o, ...pnlCalc(o) }))
      .filter((x) => !x.closed && ageBand(x.age) === bandName && (!onlyLoss || x.loss))
      .map((x) => ({ ...x, key: x.o.c, name: x.o.nm, sub: `${x.o.c}, ${x.o.dim.rl}, ${x.o.dim.zn}`, s: x.o.s }));
    const periodName = S.pm === "ytd" ? "Year to date" : fmonth(S.pm);
    const basisName = S.pbasis === "after" ? "after financing cost" : "before financing cost";
    $("#drawerTitle").textContent = `${onlyLoss ? "Loss-making outlets" : "Trading outlets"}: ${bandName}`;
    $("#drawerBody").innerHTML = mountTable("age-outlets", {
      title: `${periodName}, ${basisName}`, file: `outlets_by_age_${bandName.toLowerCase().replace(/[^a-z0-9]+/g, "_")}_${onlyLoss ? "loss" : "all"}_${S.pm}_${S.pbasis}`,
      desc: (n) => `${int(n)} outlets within the selected dashboard filters. Click an outlet for its cost breakdown.`,
      rows, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "pl", defaultDir: "asc",
      rowAttr: (x) => `data-pnl="${esc(x.key)}" tabindex="0"`,
      cols: [
        nameCol("outlet"),
        { k: "code", label: "Outlet code", val: (x) => x.key, fmt: (x) => esc(x.key), csv: (x) => x.key },
        { k: "age", label: "Age", num: 1, fmt: (x) => ageTxt(x.age), csv: (x) => x.age ?? "" },
        { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s || 0) },
        { k: "pl", label: "P/L", num: 1, fmt: (x) => `<strong class="${x.pl < 0 ? "down" : "up"}">${bdt(x.pl)}</strong>`, csv: (x) => isNum(x.pl) ? Math.round(x.pl) : "" },
        { k: "status", label: "Status", val: (x) => x.loss ? "Loss-making" : "Profitable", fmt: (x) => chip(x.loss ? LOSS_STATUS[x.st] : { cls: "good", label: "Profitable" }), csv: (x) => x.loss ? LOSS_STATUS[x.st].label : "Profitable" },
      ],
    });
    drawTable("age-outlets");
    showDrawer();
    if (context.outlet) {
      $$("[data-pnl]", $("#drawerBody")).find((row) => row.dataset.pnl === context.outlet)?.focus();
      context.outlet = null;
    }
  }
  // ---- primary reason of loss
  // Each loss-making outlet is set against the median profitable outlet of its format. Every reason gets a taka gap and the
  // biggest gap is the primary reason. Fixed costs (salary, rent, other opex) are judged against the sales the outlet should
  // make at peer sales per square foot, so low sales count as "Sales" rather than inflating every cost ratio.
  const LREASONS = ["Sales", "GP%", "Inventory gap", "Salary", "Rent", "Other income", "Outlet OPEX"];
  const lmed = (v) => { v = v.filter(isNum).sort((a, b) => a - b); return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; };
  // Cost lines for the period; year to date only when every month has a breakdown.
  function lossDetail(code) {
    const P = S.data.pnl;
    if (S.pm === "ytd" && !P.months.every((m) => Object.keys(P.detail?.[m] || {}).length)) return null;
    return detailFor(code);
  }
  function lossParts(o) {
    const det = lossDetail(o.c);
    if (!det) return null;
    const L = S.data.pnl.lines, pick = (re) => L.reduce((t, l, i) => t + (re.test(l) ? det[i] || 0 : 0), 0);
    const rent = pick(/^rent$/i), sal = pick(/salary/i), inv = pick(/stock\s+write\s*off|stock provision/i);
    return { rent, sal, inv, opx: (o.ox || 0) - rent - sal - inv };
  }
  const lossPeerCache = {};
  function lossPeers(fmt, own) {
    const key = S.pm + "|" + S.pbasis + "|" + fmt + "|" + own;
    if (lossPeerCache[key]) return lossPeerCache[key];
    const after = S.pbasis === "after";
    const every = pnlList().filter((o) => o.s >= 1 && (!fmt || o.dim.fmt === fmt) && (!own || o.dim.own === own)), list = every.filter((o) => (after ? o.p : o.g) >= 0);
    const r = (f) => lmed(list.map((o) => { const v = f(o); return isNum(v) ? v / o.s : null; }));
    const parts = list.map((o) => [o, lossParts(o)]).filter(([, x]) => x), pr = (k) => lmed(parts.map(([o, x]) => x[k] / o.s));
    return (lossPeerCache[key] = { n: list.length, gp: r((o) => o.gp), oi: r((o) => o.oi), ox: r((o) => o.ox), fin: r((o) => o.ofc || 0), rent: pr("rent"), sal: pr("sal"), inv: pr("inv"), opx: pr("opx"),
      // sales productivity is set against a typical outlet of the format (all trading outlets), not only profitable ones
      spsf: lmed(every.map((o) => (o.sft > 0 ? o.s / o.sft : null))), sales: lmed(every.map((o) => o.s)) });
  }
  function lossReason(o) {
    const fmt = o.dim.fmt !== "Not in outlet master" ? o.dim.fmt : null, own = o.dim.own === "Own" || o.dim.own === "Franchise" ? o.dim.own : null;
    // Same format and ownership when there are enough profitable peers, otherwise the whole format.
    let pe = lossPeers(fmt, own), peerOwn = own;
    if (pe.n < 5) { pe = lossPeers(fmt, null); peerOwn = null; }
    const x = lossParts(o), s = o.s;
    const fin = S.pbasis === "after" ? o.ofc || 0 : 0, finPeer = fin ? pe.fin || 0 : 0;
    const exp = o.sft > 0 && isNum(pe.spsf) ? pe.spsf * o.sft : pe.sales || s;
    const base = Math.max(s, exp);
    const cm = (pe.gp || 0) + (pe.oi || 0) - (x ? pe.inv || 0 : 0);
    const g = { Sales: exp > s ? (exp - s) * cm : 0, "GP%": isNum(pe.gp) ? pe.gp * s - (o.gp || 0) : 0, "Other income": isNum(pe.oi) ? pe.oi * s - (o.oi || 0) : 0 };
    if (x) {
      g["Inventory gap"] = x.inv - (pe.inv || 0) * s;
      g.Salary = x.sal - (pe.sal || 0) * base;
      g.Rent = x.rent - (pe.rent || 0) * base;
      g["Outlet OPEX"] = x.opx + fin - ((pe.opx || 0) + finPeer) * base;
    } else g["Outlet OPEX"] = (o.ox || 0) + fin - ((pe.ox || 0) + finPeer) * base;
    const top = Object.entries(g).sort((a, b) => b[1] - a[1])[0];
    return { reason: top[0], gap: top[1], gaps: g, exp, split: !!x, peers: pe.n, fmt: [peerOwn, fmt].filter(Boolean).join(" ") || null };
  }
  // Drawer list of outlets from the loss page, with a CSV of exactly what is shown.
  function openLossRows(title, rows, stats, file) {
    const P = S.data.pnl, ytd = S.pm === "ytd";
    rows.forEach((x) => { if (x.loss && !x.why) x.why = lossReason(x.o); });
    S.lastFocus = document.activeElement; S.ageDrill = null;
    NCSV.lossdrill = () => [file, ["Outlet code", "Outlet", "Regional leader", "Zonal", "Sales", "P/L", ...(ytd ? [] : ["P/L last month", "Change"]), "Status", "Primary reason", "Gap vs peers"],
      rows.map((x) => [x.o.c, x.o.nm, x.o.dim.rl, x.o.dim.zn, Math.round(x.o.s || 0), isNum(x.pl) ? Math.round(x.pl) : "", ...(ytd ? [] : [isNum(x.pl0) ? Math.round(x.pl0) : "", isNum(x.chg) ? Math.round(x.chg) : ""]),
        x.loss ? LOSS_STATUS[x.st]?.label || "Loss-making" : "Profitable", x.why?.reason || "", isNum(x.why?.gap) ? Math.round(x.why.gap) : ""]), ytd ? "ytd" : S.pm];
    $("#drawerTitle").textContent = title;
    $("#drawerBody").innerHTML = `<div class="stat-grid three">${stats.map(([l, v, cls]) => `<div class="stat"><small>${l}</small><strong${cls ? ` class="${cls}"` : ""}>${v}</strong></div>`).join("")}</div>
      <div class="lr-dtools"><span class="muted">${int(rows.length)} outlets. Click an outlet for its full breakdown.</span>${csvBtn("lossdrill")}</div>
      <div class="table-wrap" style="max-height:560px"><table class="compact"><thead><tr><th>Outlet</th><th class="num">Sales</th><th class="num">P/L</th>${ytd ? "" : '<th class="num">P/L last month</th>'}<th>Primary reason</th><th class="num">Gap vs peers</th></tr></thead><tbody>
      ${rows.map((x) => `<tr data-pnl="${esc(x.o.c)}" tabindex="0" class="k-click"><td><span class="cell-primary">${esc(x.o.nm)}</span><span class="cell-secondary">${esc(x.o.c)}, ${esc(x.o.dim.rl)}, ${esc(x.o.dim.zn)}</span></td><td class="num">${bdt(x.o.s)}</td><td class="num"><strong class="${x.pl < 0 ? "down" : "up"}">${bdt(x.pl)}</strong></td>${ytd ? "" : `<td class="num"><span class="${x.pl0 < 0 ? "down" : "up"}">${bdt(x.pl0)}</span></td>`}<td>${esc(x.why?.reason || "—")}</td><td class="num">${isNum(x.why?.gap) ? bdt(x.why.gap) : "—"}</td></tr>`).join("") || `<tr><td colspan="${ytd ? 5 : 6}" class="empty">No outlets.</td></tr>`}</tbody></table></div>
      <p class="muted" style="margin:0;font-size:12px">Primary reason and gap vs peers apply to loss-making outlets: the taka the reason costs against the median profitable outlet of the same format.</p>`;
    wireDyn($("#drawerBody"));
    showDrawer();
  }
  const lossRowsInView = () => inView().map((o) => ({ o, ...pnlCalc(o) })).filter((x) => !x.closed);
  const lossSlug = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  function openLossReason(reason, rl) {
    const rows = lossRowsInView().filter((x) => x.loss && (!rl || x.o.dim.rl === rl)).map((x) => ({ ...x, why: lossReason(x.o) })).filter((x) => !reason || x.why.reason === reason).sort((a, b) => a.pl - b.pl);
    openLossRows(`${reason || "All reasons"}${rl ? `, ${rl}` : ""}`, rows,
      [["Loss-making outlets", int(rows.length)], ["Total loss", bdt(rows.reduce((t, x) => t + x.pl, 0)), "down"], ["Primary reason", `<span style="font-size:18px">${esc(reason || "Any")}</span>`]],
      `loss_reason_${lossSlug(reason || "all")}${rl ? "_" + lossSlug(rl) : ""}_${S.pbasis}`);
  }
  // New losses, widening, narrowing and back to profit, from the KPI cards.
  function openLossStatus(kind) {
    const all = lossRowsInView();
    const def = {
      new: ["New losses", "Profitable last month, loss-making this month", (x) => x.loss && x.st === "new"],
      wide: ["Loss widening", "Loss-making both months, bigger loss this month", (x) => x.loss && x.st === "wide"],
      narrow: ["Loss narrowing", "Loss-making both months, smaller loss this month", (x) => x.loss && x.st === "narrow"],
      back: ["Back to profit", "Loss-making last month, profitable this month", (x) => !x.loss && isNum(x.pl0) && x.pl0 < 0],
      established: ["Established outlets in loss", "Loss-making outlets open a year or more", (x) => x.loss && x.age != null && x.age >= 12],
    }[kind];
    const rows = all.filter(def[2]).sort((a, b) => (kind === "back" ? b.pl - a.pl : a.pl - b.pl));
    const sumPl = rows.reduce((t, x) => t + (x.pl || 0), 0), sumPl0 = rows.reduce((t, x) => t + (x.pl0 || 0), 0);
    openLossRows(`${def[0]}, ${S.pm === "ytd" ? "year to date" : fmonth(S.pm)}`, rows,
      [[def[1], int(rows.length)], [S.pm === "ytd" ? "P/L year to date" : "P/L this month", `<span class="${sumPl < 0 ? "down" : "up"}">${bdt(sumPl)}</span>`], ["P/L last month", `<span class="${sumPl0 < 0 ? "down" : "up"}">${bdt(sumPl0)}</span>`]],
      `loss_${kind}_${S.pbasis}`);
  }
  function pageLoss() {
    const P = S.data.pnl;
    if (!P) return `<p class="empty">No outlet P&L file is loaded yet. Add one to the Performance folder.</p>`;
    pnlList();
    const ytd = S.pm === "ytd";
    const every = inView().map((o) => ({ o, ...pnlCalc(o) }));
    const closedL = every.filter((x) => x.closed), all = every.filter((x) => !x.closed);
    const losses = all.filter((x) => x.loss);
    const sum = (arr, k) => arr.reduce((t, x) => t + (x[k] || 0), 0);
    const totLoss = sum(losses, "pl"), net = sum(all, "pl");
    const newL = losses.filter((x) => x.st === "new").length, rec = all.filter((x) => !x.loss && isNum(x.pl0) && x.pl0 < 0).length;
    const young = losses.filter((x) => x.age != null && x.age < 12).length;
    losses.forEach((x) => (x.why = lossReason(x.o)));
    const basisLbl = S.pbasis === "after" ? "after financing cost" : "before financing cost";
    const periodName = ytd ? `year to date (${P.months.length} months)` : fmonth(S.pm);
    const monthSel = `<select class="sel" data-sel="pm" aria-label="Month">${P.months.map((m) => `<option value="${m}" ${m === S.pm ? "selected" : ""}>${fmonth(m)}</option>`).join("")}${P.months.length > 1 ? `<option value="ytd" ${ytd ? "selected" : ""}>Year to date, ${fmonth(P.months[0])} to ${fmonth(P.months[P.months.length - 1])}</option>` : ""}</select>`;
    const basisSeg = seg("pbasis", [["before", "Before financing cost"], ["after", "After financing cost"]], "P&L basis");
    const ageSeg = seg("lage", [["all", "All outlets"], ["old", "Open 1 year or more"], ["new", "Under 1 year"]], "Outlet age");

    // age bands
    const bands = [...AGE_BANDS.map((b) => b[0]), "Opening date unknown"].map((b) => {
      const inB = all.filter((x) => ageBand(x.age) === b), lB = inB.filter((x) => x.loss);
      return { b, n: inB.length, l: lB.length, loss: sum(lB, "pl") };
    }).filter((x) => x.n);
    const agePanel = `<section class="panel"><div class="panel-head"><div><h2>Loss-making outlets by age</h2><p>New outlets usually lose money while they build up trade. Click a number for the outlets.</p></div></div>
      <div class="table-wrap"><table class="compact lr-age"><thead><tr><th>Outlet age</th><th class="num">Outlets</th><th class="num">Loss-making</th><th class="num">Share</th><th class="num">Total loss</th></tr></thead><tbody>
      ${bands.map((x) => `<tr><td class="cell-primary">${esc(x.b)}</td><td class="num">${ageDrillLink(x.b, "all", int(x.n), "View all trading outlets")}</td><td class="num">${ageDrillLink(x.b, "loss", int(x.l), "View loss-making outlets")}</td><td class="num">${ageDrillLink(x.b, "loss", pct(x.l / x.n), "View outlets behind the loss-making share")}</td><td class="num down">${ageDrillLink(x.b, "loss", bdt(x.loss), "View outlets contributing to total loss", "down")}</td></tr>`).join("")}
      </tbody></table></div></section>`;

    // primary reason of loss: by regional leader, and in total
    const zero = () => Object.fromEntries(LREASONS.map((t) => [t, 0]));
    const byRl = new Map(), byR = Object.fromEntries(LREASONS.map((t) => [t, { n: 0, loss: 0 }]));
    losses.forEach((x) => {
      const k = x.o.dim.rl, r = byRl.get(k) || { k, n: 0, loss: 0, c: zero() };
      r.n++; r.loss += x.pl; r.c[x.why.reason]++; byRl.set(k, r);
      byR[x.why.reason].n++; byR[x.why.reason].loss += x.pl;
    });
    const rlRows = [...byRl.values()].sort((a, b) => b.n - a.n || a.loss - b.loss);
    const lnk = (v, reason, rl, cls = "") => (v ? `<button type="button" class="age-drill-link ${cls}" data-lreason="${esc(reason)}" data-lrl="${esc(rl)}" title="${esc(`${reason || "All loss-making outlets"}${rl ? `, ${rl}` : ""}`)}">${v}</button>` : '<span class="muted">0</span>');
    const noSplit = losses.length && !losses[0].why.split;
    const method = `Each loss-making outlet is compared with the median profitable outlet of the same format and ownership; its primary reason is the line with the biggest taka gap. Low sales are judged on sales per square foot against a typical outlet of the same format.${noSplit ? " This period has no cost-line breakdown, so Inventory gap, Salary and Rent fall under Outlet OPEX." : ""}`;
    NCSV.lreason = () => [`loss_primary_reason_${S.pm}_${S.pbasis}`, ["Regional leader", "Loss outlets", "Loss (Tk)", ...LREASONS], rlRows.map((r) => [r.k, r.n, Math.round(r.loss), ...LREASONS.map((t) => r.c[t])]).concat([["Total", losses.length, Math.round(totLoss), ...LREASONS.map((t) => byR[t].n)]]), S.pm];
    const leadPanel = `<section class="panel lr-lead"><div class="panel-head"><div><h2 class="hint-title" tabindex="0">Primary reason of loss by regional leader, ${esc(periodName)} <span class="hint-i" aria-hidden="true">ⓘ</span></h2><p class="hint-text">${method} Click a number for the outlets.</p></div><div class="panel-tools">${csvBtn("lreason")}</div></div>
      <div class="table-wrap" style="max-height:none"><table class="lr-table"><thead><tr><th>Regional leader</th><th class="num">Loss outlets</th><th class="num">Loss (Tk)</th>${LREASONS.map((t) => `<th class="num">${esc(t)}</th>`).join("")}</tr></thead><tbody>
      ${rlRows.map((r) => `<tr><td class="cell-primary">${esc(r.k)}</td><td class="num">${lnk(int(r.n), "", r.k)}</td><td class="num down">${bdt(r.loss)}</td>${LREASONS.map((t) => `<td class="num">${lnk(r.c[t] ? int(r.c[t]) : 0, t, r.k)}</td>`).join("")}</tr>`).join("")}
      </tbody><tfoot><tr class="lr-total"><td>Total</td><td class="num">${lnk(int(losses.length), "", "")}</td><td class="num down">${bdt(totLoss)}</td>${LREASONS.map((t) => `<td class="num">${lnk(byR[t].n ? int(byR[t].n) : 0, t, "")}</td>`).join("")}</tr></tfoot></table></div></section>`;
    NCSV.lreasontot = () => [`loss_by_primary_reason_${S.pm}_${S.pbasis}`, ["Primary reason", "Outlets", "Loss (Tk)"], LREASONS.map((t) => [t, byR[t].n, Math.round(byR[t].loss)]), S.pm];
    const maxL = Math.max(...LREASONS.map((t) => -byR[t].loss), 1);
    const reasonPanel = `<section class="panel"><div class="panel-head"><div><h2>Loss by primary reason, ${esc(periodName)}</h2><p>Loss-making outlets and their loss, grouped by primary reason. Click a reason for the outlets.</p></div><div class="panel-tools">${csvBtn("lreasontot")}</div></div>
      <div class="table-wrap" style="max-height:none"><table class="compact lr-rt"><thead><tr><th>Primary reason</th><th class="num">Outlets</th><th class="num">Loss (Tk)</th><th>Share of loss</th></tr></thead><tbody>
      ${LREASONS.map((t) => `<tr><td class="cell-primary">${esc(t)}</td><td class="num">${lnk(byR[t].n ? int(byR[t].n) : 0, t, "")}</td><td class="num down">${byR[t].n ? bdt(byR[t].loss) : "—"}</td><td><div class="lr-bar"><i style="width:${(-byR[t].loss / maxL) * 100}%"></i><span>${totLoss ? pct(byR[t].loss / totLoss, 0) : "—"}</span></div></td></tr>`).join("")}
      </tbody><tfoot><tr class="lr-total"><td>Total</td><td class="num">${lnk(int(losses.length), "", "")}</td><td class="num down">${bdt(totLoss)}</td><td></td></tr></tfoot></table></div></section>`;

    // by regional leader > zonal > outlet; the loss-making list below follows the drill
    const D = leaderDrill("lv", "loss-grp", all.map((x) => x.o), "click an outlet for its cost breakdown"), at = D.at, V = D.V;
    const inPath = all.filter((x) => D.inPath(x.o));
    let grpRows;
    if (at === "outlet") {
      grpRows = inPath.filter((x) => x.loss).map((x) => ({ key: x.o.c, name: x.o.nm, sub: `${x.o.c}, ${x.o.dim.zn}`, x, loss: x.pl, s: x.o.s || 0, age: x.age }));
    } else {
      const g = new Map();
      inPath.forEach((x) => { const k = x.o.dim[at]; if (!g.has(k)) g.set(k, []); g.get(k).push(x); });
      grpRows = [...g.entries()].map(([k, xs]) => { const l = xs.filter((x) => x.loss); return { key: k, name: k, sub: (() => { const t = `${int(xs.length)} outlet${xs.length === 1 ? "" : "s"}`; return at === "zn" ? D.zsub(k, t) : t; })(), n: xs.length, l: l.length, share: l.length / xs.length, loss: sum(l, "pl"), net: sum(xs, "pl"), s: xs.reduce((t, x) => t + (x.o.s || 0), 0) }; });
    }
    const nameLbl = { rl: "Regional leader", zn: "Zonal", outlet: "Outlet" }[at];
    const grp = mountTable("loss-grp", {
      title: V.zn ? `Loss-making outlets of ${V.zn}` : V.rl ? `Loss by zonal under ${V.rl}` : { rl: "Loss by regional leader", zn: "Loss by zonal", outlet: "Loss-making outlets" }[at], file: D.file(`loss_${S.pm}`), pageSize: 25,
      banner: D.crumbs, tools: D.tools,
      desc: (n) => (at === "outlet" ? `${int(n)} loss-making outlet${n === 1 ? "" : "s"}, P&L ${basisLbl}, biggest loss first. Click an outlet for its cost breakdown.` : `${int(n)} ${at === "zn" ? "zonals" : "regional leaders"}, P&L ${basisLbl}. Click ${at === "zn" ? "a zonal to list its outlets" : "a leader to see their zonals"}. The loss-making list below follows your selection.`),
      rows: grpRows, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "l", defaultDir: "desc",
      rowAttr: (x) => (at === "outlet" ? `data-pnl="${esc(x.key)}" tabindex="0"` : D.pick(x)),
      cols: at === "outlet"
        ? [{ k: "name", label: nameLbl, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name, val: (x) => x.name },
          { k: "age", label: "Age", num: 1, fmt: (x) => ageTxt(x.age), csv: (x) => x.age ?? "" },
          { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s) },
          { k: "loss", label: "P/L", num: 1, fmt: (x) => `<strong class="${x.loss < 0 ? "down" : "up"}">${bdt(x.loss)}</strong>`, csv: (x) => (isNum(x.loss) ? Math.round(x.loss) : "") },
          { k: "l", label: "Loss order", num: 1, hide: 1, nocsv: 1, val: (x) => (isNum(x.loss) ? -x.loss : null), csv: (x) => (isNum(x.loss) ? Math.round(x.loss) : "") },
          { k: "status", label: "Status", val: (x) => (x.x.loss ? "Loss-making" : "Profitable"), fmt: (x) => chip(x.x.loss ? LOSS_STATUS[x.x.st] || { cls: "bad", label: "Loss-making" } : { cls: "good", label: "Profitable" }), csv: (x) => (x.x.loss ? (LOSS_STATUS[x.x.st] || { label: "Loss-making" }).label : "Profitable") }]
        : [{ k: "name", label: nameLbl, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name, val: (x) => x.name },
          { k: "l", label: "Loss-making", num: 1, fmt: (x) => int(x.l) }, { k: "share", label: "Share", num: 1, fmt: (x) => pct(x.share), csv: (x) => pcsv(x.share) },
          { k: "loss", label: "Total loss", num: 1, fmt: (x) => `<span class="down">${bdt(x.loss)}</span>`, csv: (x) => Math.round(x.loss) },
          { k: "net", label: "Net outlet P/L", num: 1, fmt: (x) => `<span class="${x.net < 0 ? "down" : "up"}">${bdt(x.net)}</span>`, csv: (x) => Math.round(x.net) },
          { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s) }],
    });

    // outlet list
    let rows = losses.map((x) => ({ key: x.o.c, name: x.o.nm, sub: `${x.o.c}, ${x.o.dim.rl}, ${x.o.dim.zn}`, ...x, s: x.o.s }));
    if (S.pstat !== "all" && !ytd) rows = rows.filter((x) => x.st === S.pstat);
    rows = rows.filter((x) => D.inPath(x.o));
    const where = [V.rl, V.zn].filter(Boolean).join(" › ");
    const list = mountTable("loss", {
      title: `Loss-making outlets, ${periodName}`, file: `loss_making_outlets_${S.pm}${where ? "_" + where.toLowerCase().replace(/[^a-z0-9]+/g, "_") : ""}`,
      banner: where ? `<div class="drill-banner">Showing the loss-making outlets of <strong>${esc(where)}</strong> within the sidebar filters. <button type="button" data-dst="lv" data-dtab="loss-grp" data-dgo="top">Show all outlets</button></div>` : "",
      desc: (n) => `${int(n)} outlet${n === 1 ? "" : "s"}. "Break-even sales" is the sales needed to cover costs at the outlet's current margin. Click a row for the cost breakdown.`,
      rows, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "pl", defaultDir: "asc", rowAttr: (x) => `data-pnl="${esc(x.key)}" tabindex="0"`,
      tools: ytd ? "" : seg("pstat", [["all", "All"], ["new", "New loss"], ["wide", "Widening"], ["narrow", "Narrowing"]], "Loss status"),
      cols: [nameCol("outlet"),
        { k: "age", label: "Age", num: 1, fmt: (x) => ageTxt(x.age), csv: (x) => x.age ?? "" },
        { k: "s", label: "Sales", num: 1, fmt: (x) => bdt(x.s), csv: (x) => Math.round(x.s || 0) },
        { k: "gpp", label: "GP margin", num: 1, fmt: (x) => pct(x.gpp), csv: (x) => pcsv(x.gpp) },
        { k: "oxp", label: "Opex to sales", num: 1, fmt: (x) => pct(x.oxp), csv: (x) => pcsv(x.oxp) },
        { k: "pl", label: "P/L", num: 1, fmt: (x) => `<strong class="down">${bdt(x.pl)}</strong>`, csv: (x) => Math.round(x.pl) },
        ...(ytd ? [{ k: "months", label: "Months", num: 1, val: (x) => x.o.months, fmt: (x) => int(x.o.months), csv: (x) => x.o.months }] : []),
        { k: "pl0", label: "P/L last month", num: 1, fmt: (x) => `<span class="${x.pl0 < 0 ? "down" : "up"}">${bdt(x.pl0)}</span>`, csv: (x) => (isNum(x.pl0) ? Math.round(x.pl0) : "") },
        { k: "st", label: "Status", val: (x) => x.st, fmt: (x) => chip(LOSS_STATUS[x.st]), csv: (x) => LOSS_STATUS[x.st].label },
        { k: "why", label: "Primary reason", val: (x) => x.why?.reason, fmt: (x) => `<span class="cell-primary">${esc(x.why?.reason || "—")}</span><span class="cell-secondary">${isNum(x.why?.gap) ? bdt(x.why.gap) + " vs peers" : ""}</span>`, csv: (x) => x.why?.reason || "" },
        { k: "need", label: "Break-even sales", num: 1, fmt: (x) => (isNum(x.need) ? `${bdt(x.be)}<span class="cell-secondary">+${pct(x.need, 1)} needed</span>` : '<span class="muted" title="Gross margin plus other income is zero or negative">Not reachable</span>'), csv: (x) => (isNum(x.be) ? Math.round(x.be) : "") }],
    });

    if (ytd) S.tables.loss.spec.cols = S.tables.loss.spec.cols.filter((c) => c.k !== "pl0");
    return `<div class="panel-tools">${monthSel}${basisSeg}${ageSeg}</div>
      <div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      ${kpi({ hero: true, label: `Loss-making outlets, ${periodName}`, value: int(losses.length), sub: `${chip({ cls: "bad", label: pct(losses.length / (all.length || 1)) + " of outlets" })}<span>of ${int(all.length)} trading outlets, ${basisLbl}</span>`, foot: `<span>Total loss ${bdt(totLoss)}</span><span>Net outlet P/L ${bdt(net)}</span><span>${int(closedL.length)} closed outlets excluded (P/L ${bdt(sum(closedL, "pl"))})</span>`, accent: "var(--bad)" })}
      ${kpi({ label: "Total loss", value: `<span class="down">${bdt(totLoss)}</span>`, sub: "Sum of loss-making outlets", foot: `<span>Average ${bdt(losses.length ? totLoss / losses.length : null)} per outlet</span>`, accent: "var(--bad)" })}
      ${(() => { const est = losses.filter((x) => x.age != null && x.age >= 12), el = sum(est, "pl"); return kpi({ label: "Established outlets in loss", value: `<span class="down">${int(est.length)}</span>`, sub: "Open a year or more", foot: `<span>Loss ${bdt(el)}</span><span>${totLoss ? pct(el / totLoss, 0) : "—"} of total loss</span>`, accent: "var(--bad)" }).replace('<div class="kpi"', '<div class="kpi kpi-click" data-lstat="established" tabindex="0" role="button" title="List loss-making outlets open a year or more"'); })()}
      ${ytd ? "" : kpi({ label: "New losses", value: int(newL), sub: "Profitable last month", foot: `<span><button type="button" class="age-drill-link" data-lstat="wide" title="Outlets whose loss widened">Widening ${int(losses.filter((x) => x.st === "wide").length)}</button>, <button type="button" class="age-drill-link" data-lstat="narrow" title="Outlets whose loss narrowed">narrowing ${int(losses.filter((x) => x.st === "narrow").length)}</button></span>`, accent: "var(--warn)" }).replace('<div class="kpi"', '<div class="kpi kpi-click" data-lstat="new" tabindex="0" role="button" title="List the new loss-making outlets"')}
      ${ytd ? "" : kpi({ label: "Back to profit", value: `<span class="up">${int(rec)}</span>`, sub: "Loss-making last month", foot: "<span>Profitable this month</span>", accent: "var(--good)" }).replace('<div class="kpi"', '<div class="kpi kpi-click" data-lstat="back" tabindex="0" role="button" title="List the outlets back in profit"')}
      </div>
      <p class="muted" style="margin:0">${int(young)} of the ${int(losses.length)} loss-making outlets opened less than a year ago.</p>
      ${leadPanel}<div class="lr-row">${grp}<div class="lr-stack">${agePanel}${reasonPanel}</div></div>${list}`;
  }
  const peerCache = {};
  function peerMedians(fmt) {
    const P = S.data.pnl, key = S.pm + "|" + S.pbasis + "|" + fmt;
    if (peerCache[key]) return peerCache[key];
    const list = pnlList().filter((o) => (S.pbasis === "after" ? o.p : o.g) >= 0 && o.s >= 1 && detailFor(o.c) && (!fmt || o.dim.fmt === fmt)).map((o) => ({ o, d: detailFor(o.c) }));
    const med = P.lines.map((_, i) => {
      const v = list.map(({ o, d }) => (d[i] || 0) / o.s).sort((a, b) => a - b);
      return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
    });
    return (peerCache[key] = { med, n: list.length });
  }
  function openPnl(code) {
    const P = S.data.pnl, o = pnlList().find((x) => x.c === code);
    if (!o) return;
    const x = pnlCalc(o);
    const fromAgeList = !!S.ageDrill && !$("#drawer").hidden && !!$("#t-age-outlets", $("#drawerBody"));
    if (fromAgeList) S.ageDrill.outlet = code;
    else { S.ageDrill = null; S.lastFocus = document.activeElement; }
    $("#drawerTitle").textContent = `${o.c} ${o.nm}`;
    const stat = (l, v, sub = "") => `<div class="stat"><small>${l}</small><strong>${v}</strong>${sub ? `<div style="font-size:12px">${sub}</div>` : ""}</div>`;
    const det = detailFor(code);
    let costHtml = '<p class="muted" style="margin:0">No cost breakdown for this outlet in the P&L file.</p>';
    if (det) {
      const fmt = o.dim.fmt !== "Not in outlet master" ? o.dim.fmt : null;
      const peers = peerMedians(fmt);
      const items = P.lines.map((l, i) => ({ l, v: det[i] || 0, sp: o.s > 0 ? (det[i] || 0) / o.s : null, pm: peers.med[i] }))
        .filter((c) => c.v !== 0).sort((a, b) => b.v - a.v);
      costHtml = `<div class="table-wrap" style="max-height:none"><table class="compact"><thead><tr><th>Cost line</th><th class="num">Amount</th><th class="num">% of sales</th><th class="num">Profitable peers</th><th class="num">Difference</th></tr></thead><tbody>
        ${items.map((c) => { const d = isNum(c.sp) && isNum(c.pm) ? c.sp - c.pm : null; return `<tr><td class="cell-primary">${esc(c.l)}</td><td class="num">${bdt(c.v)}</td><td class="num">${pct(c.sp)}</td><td class="num">${pct(c.pm)}</td><td class="num"><span class="${d > 0.0025 ? "down" : d < -0.0025 ? "up" : "flat"}">${isNum(d) ? pp(d) : "—"}</span></td></tr>`; }).join("")}
        </tbody></table></div>
        <p class="muted" style="margin:0;font-size:12px">Peers are the median of ${int(peers.n)} profitable ${fmt ? esc(fmt.toLowerCase()) + " " : ""}outlets. Red lines cost this outlet more than 0.25 pp of sales above its peers.</p>`;
    }
    $("#drawerBody").innerHTML = `
      ${fromAgeList ? '<button type="button" class="btn age-drill-back" data-age-back>Back to outlet list</button>' : ""}
      <div class="stat-grid">
        ${stat(S.pbasis === "after" ? "P/L after financing cost" : "P/L before financing cost", `<span class="${x.pl < 0 ? "down" : "up"}">${bdt(x.pl)}</span>`, x.closed ? chip({ cls: "idle", label: "Closed outlet" }) : x.st ? chip(LOSS_STATUS[x.st]) : chip({ cls: "good", label: "Profitable" }))}
        ${S.pm === "ytd" ? stat("Months in P&L", int(o.months), "Year to date") : stat("P/L last month", bdt(x.pl0), `Change ${bdt(x.chg)}`)}
        ${stat("Sales", bdt(o.s), `${int(o.ff)} customers, bill ${bdt(o.bs)}`)}
        ${stat("GP margin", pct(x.gpp), `Other income ${bdt(o.oi)}`)}
        ${stat("Opex", bdt(o.ox), `${pct(x.oxp)} of sales`)}
        ${stat("Break-even sales", isNum(x.be) ? bdt(x.be) : "Not reachable", isNum(x.need) ? (x.need > 0 ? `+${pct(x.need, 1)} on current sales` : "Already above break-even") : "Margin plus other income is zero or negative")}
      </div>
      <dl class="facts">
        <dt>Regional leader</dt><dd>${esc(o.dim.rl)}</dd><dt>Zonal</dt><dd>${esc(o.dim.zn)}</dd>
        <dt>Format</dt><dd>${esc(o.dim.fmt)}</dd><dt>Size</dt><dd>${o.sft ? int(o.sft) + " sq ft" : "—"}</dd>
        <dt>Opened</dt><dd>${o.ld || o.m?.ld ? fdate(o.ld || o.m.ld) + ` (${ageTxt(x.age)})` : "—"}</dd><dt>Financing cost</dt><dd>${bdt(o.ofc)}</dd>
      </dl>
      ${x.loss ? (() => { const w = lossReason(o), rows = Object.entries(w.gaps).sort((a, b) => b[1] - a[1]); return `<h3 style="font-size:14px">Why it loses money</h3>
      <div class="table-wrap" style="max-height:none"><table class="compact"><thead><tr><th>Reason</th><th class="num">Gap vs peers</th></tr></thead><tbody>${rows.map(([t, v]) => `<tr${t === w.reason ? ' class="lr-top"' : ""}><td class="cell-primary">${esc(t)}${t === w.reason ? " · primary reason" : ""}</td><td class="num"><span class="${v > 0 ? "down" : "up"}">${bdt(v)}</span></td></tr>`).join("")}</tbody></table></div>
      <p class="muted" style="margin:0;font-size:12px">Positive gaps cost this outlet money against the median of ${int(w.peers)} profitable ${w.fmt ? esc(w.fmt.toLowerCase()) + " " : ""}outlets. Salary, rent and other opex are judged at the sales it should make on its floor space${isNum(w.exp) ? ` (${bdt(w.exp)})` : ""}.${w.split ? "" : " No cost-line breakdown this period, so salary, rent and inventory gap sit in Outlet OPEX."}</p>`; })() : ""}
      <h3 style="font-size:14px">Where the money goes</h3>${costHtml}`;
    if (fromAgeList) $("[data-age-back]", $("#drawerBody")).onclick = drawAgeOutlets;
    showDrawer();
  }

  // ------------------------------------------------------------------ outlet network (Outlet network + Growth & momentum)
  // data/network.json is built by scripts/network/refresh.py from the outlet-network Drive folder
  // (outlet master, day-wise target, day-wise sales, last-month SPLY). It is loaded on first visit.
  const NET_MISS = "Not recorded";
  const nnum = (v) => (isNum(v) ? v : null);
  const disp = (v) => (v == null || String(v).trim() === "" ? "—" : String(v).trim());
  const nsum = (list, k) => list.reduce((s, r) => s + (nnum(r[k]) || 0), 0);
  function compact(v) {
    if (!isNum(v)) return "—";
    const a = Math.abs(v), s = v < 0 ? "−" : "", f = (x, d) => Number(x.toFixed(d)).toString();
    return a >= 1e7 ? s + f(a / 1e7, 2) + " Cr" : a >= 1e5 ? s + f(a / 1e5, 2) + " Lac" : a >= 1e4 ? s + f(a / 1e3, 1) + " K" : s + Math.round(a).toLocaleString("en-US");
  }
  const spct = (v, d = 1) => (isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%" : "—");
  const npct = (v, d = 0) => (isNum(v) ? (v * 100).toFixed(d) + "%" : "—");
  // 99.8% must not print as 100% next to a "Watch" chip.
  const pct0 = (v) => { if (!isNum(v)) return "—"; const r = Math.round(v * 100); return (v < 1 && r >= 100) || (v > 1 && r <= 100) ? (v * 100).toFixed(1) + "%" : r + "%"; };
  const signed = (v) => (isNum(v) && v > 0 ? "+" : "") + bdt(v);
  const pn = (v) => (isNum(v) ? (v >= 0 ? "pos" : "neg") : "muted");
  const perfTone = (a) => (!isNum(a) ? { key: "idle", label: "No target" } : a >= 1 ? { key: "good", label: "On target" } : a >= 0.95 ? { key: "warn", label: "Watch" } : { key: "bad", label: "Below target" });
  const growthTone = (g) => (!isNum(g) ? { key: "idle", label: "No base" } : g >= 0.02 ? { key: "good", label: "Growing" } : g >= -0.02 ? { key: "warn", label: "Flat" } : { key: "bad", label: "Declining" });
  const tchip = (t, label) => `<span class="chip ${t.key}">${esc(label || t.label)}</span>`;
  const ratePair = (v) => (isNum(v) ? `<span class="rate-pair"><strong>${pct0(v)}</strong>${tchip(perfTone(v))}</span>` : '<span class="muted">—</span>');
  const pcsv1 = (v) => (isNum(v) ? (v * 100).toFixed(1) + "%" : "");
  const rnd = (v) => (isNum(v) ? Math.round(v) : "");

  // ---- projection maths (unchanged from the outlet network dashboard)
  const monthDays = (d) => { const [y, m] = d.split("-").map(Number); return new Date(Date.UTC(y, m, 0)).getUTCDate(); };
  const dayGroup = (d) => { const w = new Date(d + "T00:00:00Z").getUTCDay(); return w === 5 ? "friday" : w === 6 ? "saturday" : "other"; };
  const mean = (a) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : null);
  const owns = (o, k) => Object.prototype.hasOwnProperty.call(o || {}, k);
  // Actual sales to date plus separate average-sales forecasts for the remaining Fridays, Saturdays and Sun–Thu days.
  function projectMonthEnd(acts, tgts, through, days) {
    const month = through.slice(0, 7);
    const seen = Object.keys(acts || {}).filter((d) => d.startsWith(month) && d <= through).sort();
    if (!seen.length) return null;
    const toDate = seen.reduce((s, d) => s + (nnum(acts[d]) || 0), 0);
    const rest = [];
    for (let day = Number(through.slice(-2)) + 1; day <= days; day++) rest.push(month + "-" + String(day).padStart(2, "0"));
    if (!rest.length) return toDate;
    const byGroup = { friday: [], saturday: [], other: [] };
    seen.forEach((d) => byGroup[dayGroup(d)].push(nnum(acts[d]) || 0));
    const overall = toDate / seen.length;
    const seenTarget = seen.reduce((s, d) => s + (owns(tgts, d) ? nnum(tgts[d]) || 0 : 0), 0);
    const perf = seenTarget ? toDate / seenTarget : null;
    const avgs = {};
    Object.keys(byGroup).forEach((g) => {
      const actual = mean(byGroup[g]);
      if (actual !== null) { avgs[g] = actual; return; }
      const t = mean(rest.filter((d) => dayGroup(d) === g && owns(tgts, d)).map((d) => nnum(tgts[d]) || 0));
      avgs[g] = t !== null && perf !== null ? t * perf : overall;
    });
    return toDate + rest.reduce((s, d) => s + avgs[dayGroup(d)], 0);
  }
  function calcNet(base, through, from) {
    if (!through) return base.map((r) => ({ ...r }));
    const days = monthDays(through), month = through.slice(0, 7);
    const start = from && from.slice(0, 7) === month ? from : month + "-01";
    return base.map((r) => {
      const tg = r.dailySalesTargets || {}, ac = r.dailySalesActuals || {};
      const tDates = Object.keys(tg).filter((d) => d.startsWith(month)), aDates = Object.keys(ac).filter((d) => d.startsWith(month));
      const monthlyTarget = tDates.length ? tDates.reduce((s, d) => s + (nnum(tg[d]) || 0), 0) : nnum(r.monthlyTarget);
      const targetToDate = tDates.length ? tDates.filter((d) => d >= start && d <= through).reduce((s, d) => s + (nnum(tg[d]) || 0), 0) : nnum(r.targetToDate);
      const salesToDate = aDates.length ? aDates.filter((d) => d >= start && d <= through).reduce((s, d) => s + (nnum(ac[d]) || 0), 0) : nnum(r.salesToDate);
      const projectedSales = aDates.length ? projectMonthEnd(ac, tg, through, days) : nnum(r.projectedSales);
      const lastMonthSales = nnum(r.lastMonthSales);
      return {
        ...r, targetToDate, monthlyTarget, salesToDate, projectedSales, lastMonthSales,
        salesGapToDate: salesToDate !== null && targetToDate !== null ? salesToDate - targetToDate : null,
        salesAchievement: salesToDate !== null && targetToDate ? salesToDate / targetToDate : null,
        projectedGap: projectedSales !== null && monthlyTarget !== null ? projectedSales - monthlyTarget : null,
        projectedAchievement: projectedSales !== null && monthlyTarget ? projectedSales / monthlyTarget : null,
        // Month-on-month compares the projected full month against last month's full-month actual.
        momGrowth: projectedSales !== null && lastMonthSales ? projectedSales / lastMonthSales - 1 : null,
        projectedVsLastMonth: projectedSales !== null && lastMonthSales !== null ? projectedSales - lastMonthSales : null,
      };
    });
  }

  // ---- data
  function loadNet() {
    if (S.net || S.netLoading) return;
    S.netLoading = true; S.netErr = null;
    fetch("data/network.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => { prepNet(d); S.net = d; })
      .catch((e) => { S.netErr = e.message; })
      .finally(() => { S.netLoading = false; if (NET_PAGES.has(S.page) || S.page === "dq") render(); });
  }
  function prepNet(d) {
    const rows = Array.isArray(d.rows) ? d.rows : [];
    const v = (x) => (x == null || String(x).trim() === "" ? NET_MISS : String(x).trim());
    const all = new Set(), act = new Set();
    rows.forEach((r) => {
      const st = String(r.status || "").trim();
      r.status = /^own/i.test(st) ? "Own" : /^fr/i.test(st) ? "Franchise" : st;
      r.c = r.code; r.nm = r.outletName || r.code;
      r.dim = { rl: v(r.leader || r.regionalHead), zn: v(r.zonal), div: v(r.division), dis: v(r.district), fmt: v(r.format), own: v(r.status), pnp: v(r.pnpStatus),
        loc: v(r.locationType), area: v(r.area), city: v(r.cityType), floor: v(r.floorType), shape: v(r.layoutShape) };
      Object.keys(r.dailySalesTargets || {}).forEach((x) => all.add(x));
      Object.keys(r.dailySalesActuals || {}).forEach((x) => { all.add(x); act.add(x); });
    });
    const iso = (x) => /^\d{4}-\d{2}-\d{2}$/.test(x);
    const ds = [...all].filter(iso).sort(), as = [...act].filter(iso).sort();
    const src = d.source || {};
    d.rows = rows;
    d.min = ds[0] || "";
    d.max = as[as.length - 1] || ds[ds.length - 1] || "";
    d.month = src.reportMonth || d.meta?.reportMonth || d.max.slice(0, 7);
    d.lm = src.lastMonth?.monthLabel || src.previousMonthLabel || "Last month";
    d.rhKey = rows.some((r) => disp(r.regionalHead) !== "—") ? "regionalHead" : "leader";
    d.present = REG_ORDER.filter((k) => REG_ALWAYS.includes(k) || rows.some((r) => r[k] != null && String(r[k]).trim() !== ""));
    S.netTo = d.max;
    const ms = d.max ? d.max.slice(0, 8) + "01" : "";
    S.netFrom = ms && ms < d.min ? d.min : ms;
  }
  let netCache = { key: null, rows: [] };
  function netRows() {
    if (!S.net) return [];
    const range = S.page === "on" && S.netMode === "range";
    const key = `${S.netTo}|${range ? S.netFrom : ""}`;
    if (netCache.key !== key) netCache = { key, rows: calcNet(S.net.rows, S.netTo, range ? S.netFrom : "") };
    return netCache.rows;
  }
  const netLM = () => S.net?.lm || "Last month";
  function netGuard() {
    if (S.net) return "";
    loadNet();
    return S.netErr
      ? `<p class="empty">The outlet network data could not be loaded (${esc(S.netErr)}). Run the "Refresh data" workflow on GitHub, then reload this page.</p>`
      : '<p class="empty">Loading outlet network data…</p>';
  }
  function driveNote() {
    const at = S.net?.source?.drive?.syncedAt;
    const d = at ? new Date(at) : null;
    return d && !isNaN(d) ? d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Dhaka" }).replace("Sept", "Sep") : "";
  }

  // ---- grouping. Growth and change are measured only on outlets that have a last-month baseline,
  // so newly opened outlets never read as growth.
  const NET_LEVELS = { regionalHead: "Regional head", zonal: "Zonal", division: "Division", district: "District", format: "Format", area: "Area", outlet: "Outlet" };
  const netKey = (level) => (level === "regionalHead" ? S.net.rhKey : level);
  const outletLabel = (r) => (disp(r.outletName) === "—" ? disp(r.code) : `${disp(r.code)} · ${disp(r.outletName)}`);
  function netGroup(list, level, keepRows) {
    const m = new Map(), key = level === "outlet" ? null : netKey(level);
    list.forEach((r) => {
      const name = level === "outlet" ? outletLabel(r) : disp(r[key]);
      if (name === "—") return;
      const id = level === "outlet" ? r.code : name;
      let x = m.get(id);
      if (!x) m.set(id, (x = { name, sub: "", code: level === "outlet" ? r.code : null, outlets: 0, target: 0, actual: 0, monthlyTarget: 0, projected: 0, lastMonth: 0, projOnBase: 0, hasBase: 0, rows: [] }));
      x.outlets++;
      x.target += nnum(r.targetToDate) || 0; x.actual += nnum(r.salesToDate) || 0;
      x.monthlyTarget += nnum(r.monthlyTarget) || 0; x.projected += nnum(r.projectedSales) || 0;
      if (nnum(r.lastMonthSales) !== null) { x.lastMonth += r.lastMonthSales; x.projOnBase += nnum(r.projectedSales) || 0; x.hasBase++; }
      if (keepRows) x.rows.push(r);
      if (level === "outlet") x.sub = [disp(r.leader || r.regionalHead), disp(r.division)].filter((s) => s !== "—").join(" · ");
    });
    return [...m.values()].map((x) => {
      if (level !== "outlet") x.sub = `${int(x.outlets)} outlet${x.outlets === 1 ? "" : "s"}`;
      x.achievement = x.target ? x.actual / x.target : null;
      x.projectedAchievement = x.monthlyTarget ? x.projected / x.monthlyTarget : null;
      x.mom = x.lastMonth ? x.projOnBase / x.lastMonth - 1 : null;
      x.delta = x.lastMonth ? x.projOnBase - x.lastMonth : null;
      return x;
    });
  }
  function countBy(list, get) {
    const m = new Map();
    list.forEach((r) => { const v = get(r); if (v && v !== "—") m.set(v, (m.get(v) || 0) + 1); });
    return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  }
  function baseTotals(list) {
    const withBase = list.filter((r) => nnum(r.lastMonthSales) !== null);
    const lastTotal = withBase.reduce((s, r) => s + r.lastMonthSales, 0);
    const projOnBase = withBase.reduce((s, r) => s + (nnum(r.projectedSales) || 0), 0);
    return { withBase, lastTotal, projOnBase, growth: lastTotal ? projOnBase / lastTotal - 1 : null, change: lastTotal ? projOnBase - lastTotal : null };
  }

  // ---- shared bits: drill-to-register, CSV, segmented controls, hero card, charts
  const NDRILL = new Map();
  let ndSeq = 0;
  const ndrill = (fn) => { const id = "n" + ++ndSeq; NDRILL.set(id, fn); return `data-ndrill="${id}"`; };
  const dbtn = (label, title, fn) => `<button class="drill" type="button" title="${esc(title)}" ${ndrill(fn)}>${esc(label)}</button>`;
  function setDrill(label, values, get) {
    const want = new Set(values.map((x) => String(x).toLowerCase()));
    S.on.drill = { label, values, test: (r) => want.has(String(get(r)).toLowerCase()) };
    if (S.tables["on-reg"]) S.tables["on-reg"].page = 1;
    render();
    requestAnimationFrame(() => $("#t-on-reg")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
  const levelDrill = (level, name) => { const key = netKey(level); setDrill(NET_LEVELS[level], [name], (r) => disp(r[key])); };
  const NCSV = {};
  function saveCsv(name, header, rows, stamp) {
    const q = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const blob = new Blob(["﻿" + [header].concat(rows).map((r) => r.map(q).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${name}_${stamp || S.netTo || "data"}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const csvBtn = (k) => `<button class="btn" data-ncsv="${k}">Download CSV</button>`;
  // path like "on.league" → S.on.league
  const nseg = (path, opts, label) => { const [a, b] = path.split("."); return `<div class="seg" role="group" aria-label="${esc(label)}">${opts.map(([v, t]) => `<button data-nset="${path}" data-val="${v}" aria-pressed="${S[a][b] === v}">${esc(t)}</button>`).join("")}</div>`; };
  function netHero(o) {
    const scaleMax = Math.max(1.2, isNum(o.ratio) ? Math.min(o.ratio, 2) : 0);
    const fill = isNum(o.ratio) ? (Math.min(o.ratio, scaleMax) / scaleMax) * 100 : 0;
    return `<div class="kpi hero net-hero" style="--accent:var(--series-2)">
      <div class="hero-grid"><div class="hero-figure"><span class="label">${esc(o.label)}</span><span class="value" title="${esc(o.title || "")}">${o.value}</span><span class="sub">${o.sub}</span></div>
      <dl class="hero-rows">${o.rows.map(([dt, dd, cls]) => `<div class="hero-row"><dt>${esc(dt)}</dt><dd class="${cls || ""}">${dd}</dd></div>`).join("")}</dl></div>
      <div class="meter" role="img" aria-label="${esc(o.aria)}"><i class="${isNum(o.ratio) ? o.tone.key : ""}" style="width:${fill.toFixed(1)}%"></i><b style="left:${(100 / scaleMax).toFixed(1)}%"></b></div>
      <div class="meter-scale"><span>0</span><span>${esc(o.scale)}</span></div>
      <span class="foot">${o.foot}</span></div>`;
  }
  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  // SVG presentation attributes don't reliably take var(), so charts resolve tokens and redraw on a theme switch.
  function palette() { const memo = {}; return (n) => memo[n] || (memo[n] = cssVar(n) || "#888888"); }
  const SVG_NS = "http://www.w3.org/2000/svg";
  function svgEl(name, attrs = {}) {
    const el = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([k, v]) => { if (v != null) el.setAttribute(k, v); });
    return el;
  }
  function readableInk(hex) {
    const m = String(hex).trim().replace("#", ""), full = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
    if (!/^[0-9a-f]{6}$/i.test(full)) return "#0a141c";
    const [r, g, b] = [0, 2, 4].map((i) => { const c = parseInt(full.slice(i, i + 2), 16) / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); });
    const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? "#ffffff" : "#0a141c";
  }
  let tipEl = null;
  function showTip(evt, html) {
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "viz-tooltip"; tipEl.setAttribute("role", "status"); document.body.append(tipEl); }
    tipEl.innerHTML = html; tipEl.classList.add("is-visible");
    const pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
    tipEl.style.left = Math.max(8, x) + "px"; tipEl.style.top = Math.max(8, y) + "px";
  }
  const hideTip = () => tipEl?.classList.remove("is-visible");
  const attachTip = (node, html) => { node.addEventListener("pointerenter", (e) => showTip(e, html())); node.addEventListener("pointermove", (e) => showTip(e, html())); node.addEventListener("pointerleave", hideTip); };
  function dateControls(rangeAllowed) {
    const d = S.net, range = rangeAllowed && S.netMode === "range";
    const inp = (k, lbl, min, max) => `<label class="net-date">${lbl}<input type="date" data-ndate="${k}" value="${esc(S[k])}" min="${min}" max="${max}"></label>`;
    const mode = `<div class="seg" role="group" aria-label="Sales period">${[["through", "Through date"], ["range", "Date range"]].map(([v, t]) => `<button data-nset="netm.mode" data-val="${v}" aria-pressed="${S.netMode === v}">${t}</button>`).join("")}</div>`;
    return (rangeAllowed ? mode : "")
      + (range ? inp("netFrom", "From", d.min, S.netTo) + inp("netTo", "To", S.netFrom, d.max) : inp("netTo", rangeAllowed ? "Month start through" : "Sales through", d.min, d.max));
  }

  // ---- Outlet network page
  const REG_ORDER = ["code", "outletName", "targetToDate", "salesToDate", "salesGapToDate", "salesAchievement", "lastMonthSales", "momGrowth", "projectedVsLastMonth", "monthlyTarget", "projectedSales", "projectedGap", "projectedAchievement",
    "leader", "rhoId", "rhoPhone", "zonal", "zonalId", "zonalPhone", "format", "division", "district", "cityType", "floorType", "layoutShape", "status", "pnpStatus", "sft", "launchDate", "locationType", "regionalHead", "area", "density", "incomeLevel"];
  const REG_KEY = ["code", "targetToDate", "salesToDate", "salesAchievement", "lastMonthSales", "momGrowth", "monthlyTarget", "projectedSales", "projectedAchievement", "regionalHead", "zonal", "division", "format"];
  const REG_ALWAYS = ["targetToDate", "salesToDate", "salesGapToDate", "salesAchievement", "lastMonthSales", "momGrowth", "projectedVsLastMonth", "monthlyTarget", "projectedSales", "projectedGap", "projectedAchievement"];
  const REG_MONEY = ["salesToDate", "targetToDate", "salesGapToDate", "lastMonthSales", "projectedVsLastMonth", "monthlyTarget", "projectedSales", "projectedGap"];
  const REG_PCT = ["salesAchievement", "projectedAchievement", "momGrowth"];
  const REG_SIGNED = ["salesGapToDate", "projectedGap", "projectedVsLastMonth"];
  const REG_LABELS = {
    code: "Outlet", outletName: "Outlet name", targetToDate: "Target (TD)", salesToDate: "Actual (TD)", salesGapToDate: "Gap (TD)", salesAchievement: "Achievement (TD)", momGrowth: "MoM growth",
    projectedVsLastMonth: "Projected vs last month", monthlyTarget: "Monthly target", projectedSales: "Projected", projectedGap: "Projected gap", projectedAchievement: "Projected ach.",
    leader: "Leader", regionalHead: "Regional head", rhoId: "RHO ID", rhoPhone: "RHO phone", zonal: "Zonal", zonalId: "Zonal ID", zonalPhone: "Zonal phone", format: "Format", division: "Division", district: "District",
    pnpStatus: "PNP status", status: "Store status", sft: "SFT", launchDate: "Launch date", locationType: "Location type", cityType: "Dv / Ds / T", floorType: "Floor type", layoutShape: "Layout shape",
    area: "Area", density: "Density", incomeLevel: "Income level",
  };
  function regCol(k) {
    const numeric = REG_MONEY.includes(k) || REG_PCT.includes(k) || k === "sft";
    const label = k === "lastMonthSales" ? netLM() + " sales" : REG_LABELS[k] || k;
    const col = { k, label, num: numeric ? 1 : 0, val: numeric ? (r) => nnum(r[k]) : (r) => disp(r[k]) };
    if (k === "code") Object.assign(col, { val: (r) => r.code, csv: (r) => r.code, csvLabel: "Outlet Code",
      fmt: (r) => `<span class="cell-primary">${esc(disp(r.code))}</span><span class="cell-secondary" title="${esc(disp(r.outletName))}">${esc(disp(r.outletName))}</span>` });
    else if (REG_MONEY.includes(k)) Object.assign(col, { csv: (r) => rnd(r[k]),
      fmt: (r) => { const n = nnum(r[k]), s = REG_SIGNED.includes(k); return `<span class="${s && n !== null ? pn(n) : ""}" title="${esc(exact(n))}">${s ? signed(n) : bdt(n)}</span>`; } });
    else if (k === "momGrowth") Object.assign(col, { csv: (r) => pcsv1(r[k]), fmt: (r) => `<span class="${pn(nnum(r[k]))}">${spct(nnum(r[k]))}</span>` });
    else if (REG_PCT.includes(k)) Object.assign(col, { csv: (r) => pcsv1(r[k]), fmt: (r) => ratePair(nnum(r[k])) });
    else if (k === "sft") Object.assign(col, { csv: (r) => r.sft ?? "", fmt: (r) => (nnum(r.sft) ? int(r.sft) : "—") });
    else if (k === "launchDate") Object.assign(col, { csv: (r) => r.launchDate || "", fmt: (r) => (r.launchDate ? fdate(r.launchDate) : "—") });
    else Object.assign(col, { csv: (r) => r[k] ?? "", fmt: (r) => esc(disp(r[k])) });
    return col;
  }
  function pageON() {
    const g = netGuard(); if (g) return g;
    NDRILL.clear();
    const d = S.net, st = S.on, lm = netLM(), list = inView(), all = baseList();
    const range = S.netMode === "range";
    const periodLabel = range ? `${fdate(S.netFrom)} – ${fdate(S.netTo)}` : `1 – ${fdate(S.netTo)}`;

    // sales performance
    const t = nsum(list, "targetToDate"), a = nsum(list, "salesToDate"), mt = nsum(list, "monthlyTarget"), p = nsum(list, "projectedSales");
    const b = baseTotals(list), ach = t ? a / t : null, pach = mt ? p / mt : null, gap = p - mt, tdGap = a - t;
    const tdTone = perfTone(ach), pjTone = perfTone(pach), gTone = growthTone(b.growth);
    NCSV.sales = () => ["outlet_network_sales", ["Measure", "Value"], [
      ["Period", periodLabel], ["Outlets in view", list.length], ["Target till date", rnd(t)], ["Actual till date", rnd(a)], ["Gap till date", rnd(tdGap)],
      ["Achievement till date", pcsv1(ach)], ["Monthly target", rnd(mt)], ["Projected month-end", rnd(p)], ["Projected gap", rnd(gap)], ["Projected achievement", pcsv1(pach)],
      [`${lm} sales (outlets with a baseline)`, rnd(b.lastTotal)], ["Outlets with a baseline", b.withBase.length], ["Projected on baseline outlets", rnd(b.projOnBase)], ["MoM growth", pcsv1(b.growth)]]];
    const sales = `<section class="panel"><div class="panel-head"><div><h2>Sales performance</h2><p>${range ? `Target and actual for ${fdate(S.netFrom)} to ${fdate(S.netTo)}. The month-end projection still uses actual sales from the 1st.` : `Month start through ${fdate(S.netTo)}, with the month-end projection.`}</p></div>
      <div class="panel-tools">${dateControls(true)}${csvBtn("sales")}</div></div>
      <div class="panel-body"><div class="kpis net-kpis">
      ${netHero({ label: "Projected month-end", value: bdt(p || null), title: exact(p), sub: `${tchip(pjTone)} ${pct0(pach)} of monthly target`, ratio: pach, tone: pjTone, aria: `Projected ${pct0(pach)} of monthly target`, scale: "Target",
        rows: [["Monthly target", bdt(mt || null)], ["Gap to target", mt ? signed(gap) : "—", gap >= 0 ? "pos" : "neg"], [`${lm} actual`, bdt(b.lastTotal || null)]],
        foot: `<span>Friday, Saturday and Sun–Thu run rates</span><span>${int(list.length)} outlets</span>` })}
      ${kpi({ label: "Actual till date", value: bdt(a || null), sub: tchip(tdTone, pct0(ach) + " · " + tdTone.label), foot: `<span>${esc(periodLabel)}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: "Target till date", value: bdt(t || null), sub: `Gap <strong class="${tdGap >= 0 ? "pos" : "neg"}">${t ? signed(tdGap) : "—"}</strong>`, foot: "<span>Sum of daily targets in the period</span>", accent: "var(--line)" })}
      ${kpi({ label: `${esc(lm)} sales`, value: bdt(b.lastTotal || null), sub: `${int(b.withBase.length)} of ${int(list.length)} outlets have a baseline`, foot: "<span>Full-month actual</span>", accent: "var(--series-3)" })}
      ${kpi({ label: "Month on month", value: `<span class="${pn(b.growth)}">${spct(b.growth)}</span>`, sub: tchip(gTone), foot: `<span>${b.change === null ? "No baseline" : `${b.change >= 0 ? "▲" : "▼"} ${bdt(Math.abs(b.change))} projected vs ${esc(lm)}`}</span>`, accent: "var(--series-4)" })}
      </div></div></section>`;

    // network at a glance
    const sfts = list.map((r) => nnum(r.sft)).filter((n) => n > 0), area = sfts.reduce((s, n) => s + n, 0);
    const own = list.filter((r) => r.status === "Own"), pnp = list.filter((r) => String(r.pnpStatus).toUpperCase() === "PNP");
    const launches = list.map((r) => r.launchDate).filter((x) => /^\d{4}-\d{2}-\d{2}$/.test(x || "")).sort();
    const ly = launches.length ? launches[launches.length - 1].slice(0, 4) : null, lmo = launches.length ? launches[launches.length - 1].slice(0, 7) : null;
    const yc = ly ? launches.filter((x) => x.startsWith(ly)).length : 0, mc = lmo ? launches.filter((x) => x.startsWith(lmo)).length : 0;
    const share = (n) => pct0(list.length ? n / list.length : null) + " of outlets";
    const glance = [
      ["Outlets", int(list.length), "In the current view"],
      ["Total floor area", compact(area), "sft across valid records"],
      ["Average size", sfts.length ? int(area / sfts.length) : "—", "sft per outlet"],
      ["Own stores", own.length ? dbtn(int(own.length), "List own stores", () => setDrill("Store status", ["Own"], (r) => r.status)) : "0", share(own.length)],
      ["PNP outlets", pnp.length ? dbtn(int(pnp.length), "List PNP outlets", () => setDrill("PNP status", ["PNP"], (r) => String(r.pnpStatus).toUpperCase())) : "0", share(pnp.length)],
      [`Opened in ${ly || "latest year"}`, yc ? dbtn(int(yc), `List outlets opened in ${ly}`, () => setDrill("Launch year", [ly], (r) => (r.launchDate || "").slice(0, 4))) : "—", "Latest launch year"],
      [`Opened in ${lmo ? fmonth(lmo) : "latest month"}`, mc ? dbtn(int(mc), `List outlets opened in ${fmonth(lmo)}`, () => setDrill("Launch month", [lmo], (r) => (r.launchDate || "").slice(0, 7))) : "—", "Latest launch month"],
    ];
    const glanceHtml = `<section class="panel"><div class="panel-head"><div><h2>Network at a glance</h2><p>Blue figures open the matching outlets in the outlet register.</p></div></div>
      <div class="stat-strip">${glance.map(([l, v, n]) => `<div><span>${esc(l)}</span><strong>${v}</strong><small>${esc(n)}</small></div>`).join("")}</div></section>`;

    // actual vs target by level
    const lvl = st.league, lvlName = NET_LEVELS[lvl];
    const leagueRows = netGroup(list, lvl);
    const league = mountTable("on-league", {
      title: `Actual vs target by ${lvlName.toLowerCase()}`, file: `${lvl}_actual_vs_target`, stamp: S.netTo,
      desc: (n) => `${int(n)} ${lvlName.toLowerCase()} groups. Click a row to list its outlets in the register. Group results are sums of their outlets, never averages of outlet percentages.`,
      rows: leagueRows, key: (x) => x.name, searchText: (x) => x.name, defaultSort: "actual", pageSize: 25,
      tools: `<select class="sel" data-nsel="on.league" aria-label="Level">${["regionalHead", "zonal", "division", "district", "format", "area"].map((k) => `<option value="${k}" ${lvl === k ? "selected" : ""}>${NET_LEVELS[k]}</option>`).join("")}</select>`,
      rowAttr: (x) => `${ndrill(() => levelDrill(lvl, x.name))} tabindex="0" title="List ${esc(x.name)}'s outlets" style="cursor:pointer"`,
      cols: [
        { k: "name", label: lvlName, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span>`, csv: (x) => x.name },
        { k: "outlets", label: "Outlets", num: 1, fmt: (x) => int(x.outlets) },
        { k: "target", label: "Target (TD)", num: 1, fmt: (x) => bdt(x.target), csv: (x) => rnd(x.target) },
        { k: "actual", label: "Actual (TD)", num: 1, fmt: (x) => `<strong>${bdt(x.actual)}</strong>`, csv: (x) => rnd(x.actual) },
        { k: "achievement", label: "Achievement (TD)", num: 1, fmt: (x) => ratePair(x.achievement), csv: (x) => pcsv1(x.achievement) },
        { k: "lastMonth", label: lm, num: 1, fmt: (x) => bdt(x.lastMonth || null), csv: (x) => rnd(x.lastMonth) },
        { k: "monthlyTarget", label: "Monthly target", num: 1, fmt: (x) => bdt(x.monthlyTarget), csv: (x) => rnd(x.monthlyTarget) },
        { k: "projected", label: "Projected", num: 1, fmt: (x) => `<strong>${bdt(x.projected)}</strong>`, csv: (x) => rnd(x.projected) },
        { k: "projectedAchievement", label: "Projected ach.", num: 1, fmt: (x) => ratePair(x.projectedAchievement), csv: (x) => pcsv1(x.projectedAchievement) },
        { k: "mom", label: "MoM growth", num: 1, fmt: (x) => `<span class="${pn(x.mom)}">${spct(x.mom)}</span>`, csv: (x) => pcsv1(x.mom) },
      ],
    });

    // outlets overseen
    const ovKey = st.oversight === "regional" ? "regionalHead" : "zonal", ovName = st.oversight === "regional" ? "Regional head" : "Zonal";
    const ov = netGroup(list, ovKey).sort((x, y) => y.outlets - x.outlets || x.name.localeCompare(y.name));
    NCSV.oversight = () => [`outlets_overseen_${st.oversight}`, [ovName, "Outlets overseen", "Target till date", "Actual till date", `${lm} sales`, "Monthly target", "Projected month-end", "MoM growth", "Till-date achievement"],
      ov.map((x) => [x.name, x.outlets, rnd(x.target), rnd(x.actual), rnd(x.lastMonth), rnd(x.monthlyTarget), rnd(x.projected), pcsv1(x.mom), pcsv1(x.achievement)])];
    const ovMax = Math.max(1, ...ov.map((x) => x.outlets));
    const oversight = `<section class="panel"><div class="panel-head"><div><h2>Outlets overseen</h2><p>Outlets per ${ovName.toLowerCase()}, with projected growth against ${esc(lm)}.</p></div>
      <div class="panel-tools">${nseg("on.oversight", [["regional", "Regional head"], ["zonal", "Zonal"]], "Oversight level")}${csvBtn("oversight")}</div></div>
      <div class="panel-body"><div class="rank-list scroll">${ov.map((x) => `<div class="rank-row">
        <div class="rank-name"><strong title="${esc(x.name)}">${esc(x.name)}</strong><span>${bdt(x.projected)} projected</span></div>
        <div class="bar-track"><i class="bar-fill" style="width:${((x.outlets / ovMax) * 100).toFixed(1)}%"></i></div>
        <div class="rank-value">${dbtn(int(x.outlets), `List ${x.name}'s outlets`, () => levelDrill(ovKey, x.name))}</div>
        <div class="rank-value ${pn(x.mom)}" title="Month-on-month growth">${spct(x.mom)}</div></div>`).join("") || '<p class="net-empty">No outlets in view have a value for this level.</p>'}</div></div></section>`;

    const shareBars = (title, sub, key, label) => {
      const items = countBy(list, (r) => disp(r[key])), tot = items.reduce((s, x) => s + x.value, 0) || 1, max = Math.max(1, ...items.map((x) => x.value));
      return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p>${sub}</p></div></div><div class="panel-body"><div class="rank-list scroll">
        ${items.map((x) => `<div class="rank-row"><div class="rank-name"><strong title="${esc(x.label)}">${esc(x.label)}</strong></div>
          <div class="bar-track"><i class="bar-fill" style="width:${((x.value / max) * 100).toFixed(1)}%"></i></div>
          <div class="rank-value">${dbtn(int(x.value), `List ${x.label} outlets`, () => setDrill(label, [x.label], (r) => disp(r[key])))}</div>
          <div class="rank-value muted">${Math.round((x.value / tot) * 100)}%</div></div>`).join("") || '<p class="net-empty">No outlets in view have this field.</p>'}</div></div></section>`;
    };
    const COLORS = ["--series-2", "--series-1", "--series-3", "--series-4", "--idle"];
    const donut = (title, key) => {
      let parts = countBy(list, (r) => disp(r[key]));
      if (parts.length > 5) { const rest = parts.slice(4); parts = parts.slice(0, 4).concat({ label: "Other", value: rest.reduce((s, x) => s + x.value, 0), values: rest.map((x) => x.label) }); }
      const total = parts.reduce((s, x) => s + x.value, 0);
      if (!total) return `<div class="mix"><h3>${esc(title)}</h3><p class="net-empty">No data.</p></div>`;
      let acc = 0;
      const stops = parts.map((x, i) => { const from = (acc / total) * 100; acc += x.value; return `var(${COLORS[i]}) ${from.toFixed(2)}% ${((acc / total) * 100).toFixed(2)}%`; }).join(", ");
      return `<div class="mix"><h3>${esc(title)}</h3><div class="mix-body">
        <div class="donut" role="img" aria-label="${esc(title)}: ${esc(parts.map((x) => `${x.label} ${x.value}`).join(", "))}" style="background:conic-gradient(${stops})"><div class="donut-center"><strong>${int(total)}</strong><span>outlets</span></div></div>
        <ul class="legend">${parts.map((x, i) => `<li><i style="background:var(${COLORS[i]})"></i><span title="${esc(x.label)}">${esc(x.label)}</span>
          ${dbtn(`${int(x.value)} · ${Math.round((x.value / total) * 100)}%`, `List ${x.label} outlets`, () => setDrill(title, x.values || [x.label], (r) => disp(r[key])))}</li>`).join("")}</ul></div></div>`;
    };
    const mix = `<section class="panel"><div class="panel-head"><div><h2>Portfolio mix</h2><p>Share of outlets by format, store status and PNP status.</p></div></div>
      <div class="panel-body"><div class="mix-grid">${donut("Format", "format")}${donut("Store status", "status")}${donut("PNP status", "pnpStatus")}</div></div></section>`;

    // outlet openings
    const year = (d.month || S.netTo).slice(0, 4), byMonth = st.launch === "month";
    const buckets = new Map();
    list.forEach((r) => {
      const ld = r.launchDate;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(ld || "")) return;
      if (byMonth && ld.slice(0, 4) !== year) return;
      const key = byMonth ? ld.slice(0, 7) : ld.slice(0, 4);
      const x = buckets.get(key) || { key, label: byMonth ? fmonth(key) : key, outlets: 0, sft: 0, sftN: 0, lastMonth: 0, projOnBase: 0, projected: 0, actual: 0 };
      x.outlets++;
      if (nnum(r.sft) > 0) { x.sft += r.sft; x.sftN++; }
      if (nnum(r.lastMonthSales) !== null) { x.lastMonth += r.lastMonthSales; x.projOnBase += nnum(r.projectedSales) || 0; }
      x.projected += nnum(r.projectedSales) || 0; x.actual += nnum(r.salesToDate) || 0;
      buckets.set(key, x);
    });
    const cohorts = [...buckets.values()].sort((x, y) => (byMonth ? x.key.localeCompare(y.key) : y.key.localeCompare(x.key)))
      .map((x) => ({ ...x, avgSft: x.sftN ? x.sft / x.sftN : null, mom: x.lastMonth ? x.projOnBase / x.lastMonth - 1 : null, share: x.outlets / (list.length || 1) }));
    NCSV.launch = () => [`outlet_openings_${byMonth ? year + "_by_month" : "by_year"}`, [byMonth ? "Launch month" : "Launch year", "Outlets opened", "Total SFT", "Average SFT", "Actual till date", `${lm} sales`, "Projected month-end", "MoM growth", "Share of outlets in view"],
      cohorts.map((x) => [x.label, x.outlets, rnd(x.sft), rnd(x.avgSft), rnd(x.actual), rnd(x.lastMonth), rnd(x.projected), pcsv1(x.mom), pcsv1(x.share)])];
    const maxShare = Math.max(0.0001, ...cohorts.map((x) => x.share));
    const launch = `<section class="panel"><div class="panel-head"><div><h2>Outlet openings</h2><p>${byMonth ? `Openings month by month across ${year}, and how each month's cohort is trading now.` : "Cohort size, floor area and how each opening cohort is trading now."}</p></div>
      <div class="panel-tools">${nseg("on.launch", [["year", "By launch year"], ["month", `${year} by month`]], "Opening grouping")}${csvBtn("launch")}</div></div>
      ${cohorts.length ? `<div class="table-wrap" style="max-height:460px"><table><thead><tr><th>${byMonth ? "Launch month" : "Launch year"}</th><th class="num">Outlets</th><th>Share of outlets</th><th class="num">Total sft</th><th class="num">Average sft</th><th class="num">Actual (TD)</th><th class="num">${esc(lm)}</th><th class="num">Projected</th><th class="num">MoM growth</th></tr></thead><tbody>
        ${cohorts.map((x) => `<tr><td class="cell-primary">${esc(x.label)}</td>
          <td class="num">${dbtn(int(x.outlets), `List outlets opened in ${x.label}`, () => setDrill(byMonth ? "Launch month" : "Launch year", [x.key], (r) => (r.launchDate || "").slice(0, byMonth ? 7 : 4)))}</td>
          <td style="min-width:150px"><div style="display:grid;grid-template-columns:minmax(60px,1fr) 36px;gap:8px;align-items:center"><div class="bar-track"><i class="bar-fill" style="width:${((x.share / maxShare) * 100).toFixed(1)}%"></i></div><span class="rank-value muted">${Math.round(x.share * 100)}%</span></div></td>
          <td class="num">${x.sft ? compact(x.sft) : "—"}</td><td class="num">${x.avgSft ? int(x.avgSft) : "—"}</td><td class="num">${bdt(x.actual)}</td>
          <td class="num">${bdt(x.lastMonth || null)}</td><td class="num"><strong>${bdt(x.projected)}</strong></td><td class="num ${pn(x.mom)}">${spct(x.mom)}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="net-empty">${byMonth ? `No outlets opened in ${year} within the current filters.` : "No valid launch dates in the current view."}</p>`}</section>`;

    // outlet register
    const drill = st.drill, regRows = drill ? list.filter(drill.test) : list;
    const present = d.present, rk = d.rhKey;
    const shown = st.cols === "all" ? present : REG_KEY.map((k) => (k === "regionalHead" ? rk : k)).filter((k) => present.includes(k));
    const register = mountTable("on-reg", {
      title: "Outlet register", file: "outlet_register", stamp: S.netTo,
      desc: (n) => `${int(n)} outlet${n === 1 ? "" : "s"} after filters and search. Click a row for the outlet profile. The CSV always has every column.`,
      banner: drill ? `<div class="drill-banner">Showing <strong>${esc(drill.label)}: ${esc(drill.values.map((x) => (/^\d{4}-\d{2}$/.test(x) ? fmonth(x) : x)).join(", "))}</strong> within the sidebar filters. <button type="button" data-ndrill-clear>Show all outlets</button></div>` : "",
      rows: regRows, key: (r) => r.code, defaultSort: "projectedSales",
      searchText: (r) => REG_ORDER.map((k) => r[k] ?? "").join(" "),
      tools: nseg("on.cols", [["key", "Key columns"], ["all", "All columns"]], "Columns"),
      rowAttr: (r) => `data-noutlet="${esc(r.code)}" tabindex="0"`,
      cols: shown.map(regCol), csvCols: present.map(regCol),
    });

    return `${sales}${glanceHtml}${league}
      <div class="grid-h net-eq">${oversight}${mix}</div>
      <div class="grid-h net-eq">${shareBars("Location type", "Where outlets trade.", "locationType", "Location type")}${shareBars("Coverage by division", "Outlet count and share of the outlets in view.", "division", "Division")}</div>
      ${launch}${register}
      <p class="muted" style="margin:0;font-size:11.5px">Outlet network data from the mother Google Drive folder${driveNote() ? `, synced ${esc(driveNote())}` : ""}. ${d.source?.lastMonth?.matchedOutlets ? `${esc(lm)} baseline on ${int(d.source.lastMonth.matchedOutlets)} outlets.` : ""}</p>`;
  }

  // ---- Growth & momentum page
  const WEEKDAYS = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"];
  const SEQ = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
  const QUADS = {
    accelerating: { key: "accelerating", label: "Accelerating", glyph: "▲", color: "--good", note: "Growing and on target" },
    holding: { key: "holding", label: "Holding", glyph: "●", color: "--info", note: "On target but slowing" },
    catching: { key: "catching", label: "Catching up", glyph: "◆", color: "--warn", note: "Growing but short of target" },
    atrisk: { key: "atrisk", label: "At risk", glyph: "▼", color: "--bad", note: "Declining and below target" },
  };
  function quadOf(g, a) {
    g = isNum(g) ? g : 0; a = isNum(a) ? a : 0;
    return g >= 0 && a >= 1 ? QUADS.accelerating : g < 0 && a >= 1 ? QUADS.holding : g >= 0 ? QUADS.catching : QUADS.atrisk;
  }
  function dailyNetwork(list) {
    const month = S.net.month;
    if (!/^\d{4}-\d{2}$/.test(month || "")) return [];
    const days = monthDays(month + "-01"), through = S.netTo || "", out = [];
    for (let dd = 1; dd <= days; dd++) { const iso = `${month}-${String(dd).padStart(2, "0")}`; out.push({ date: iso, day: dd, actual: 0, target: 0, observed: through ? iso <= through : true }); }
    const idx = new Map(out.map((o) => [o.date, o]));
    list.forEach((r) => {
      Object.entries(r.dailySalesActuals || {}).forEach(([k, v]) => { const o = idx.get(k); if (o && o.observed) o.actual += nnum(v) || 0; });
      Object.entries(r.dailySalesTargets || {}).forEach(([k, v]) => { const o = idx.get(k); if (o) o.target += nnum(v) || 0; });
    });
    return out;
  }
  function weekdayTotals(daily) {
    const w = WEEKDAYS.map((name) => ({ name, total: 0, days: 0, avg: 0 }));
    daily.forEach((x) => { if (!x.observed || x.actual <= 0) return; const i = (new Date(x.date + "T00:00:00Z").getUTCDay() + 1) % 7; w[i].total += x.actual; w[i].days++; });
    w.forEach((x) => (x.avg = x.days ? x.total / x.days : 0));
    return w;
  }
  const GM_LEVELS = [["regionalHead", "Regional head"], ["zonal", "Zonal"], ["outlet", "Outlet"]];
  function pageGM() {
    const g = netGuard(); if (g) return g;
    NDRILL.clear();
    const st = S.gm, lm = netLM(), list = inView();

    // hero
    const b = baseTotals(list);
    const projTotal = nsum(list, "projectedSales"), monthlyTarget = nsum(list, "monthlyTarget"), targetToDate = nsum(list, "targetToDate"), actualToDate = nsum(list, "salesToDate");
    const ach = monthlyTarget ? projTotal / monthlyTarget : null, achToDate = targetToDate ? actualToDate / targetToDate : null;
    const growing = b.withBase.filter((r) => nnum(r.momGrowth) > 0.02).length, declining = b.withBase.filter((r) => nnum(r.momGrowth) !== null && r.momGrowth < -0.02).length;
    const flat = b.withBase.length - growing - declining;
    const daily = dailyNetwork(list), observed = daily.filter((x) => x.observed && x.actual > 0);
    const runRate = observed.length ? observed.reduce((s, x) => s + x.actual, 0) / observed.length : null;
    const remaining = daily.filter((x) => !x.observed).length;
    const neededRate = remaining && monthlyTarget ? Math.max(0, monthlyTarget - actualToDate) / remaining : null;
    const pjTone = perfTone(ach), tdTone = perfTone(achToDate);
    const shareOf = (n) => (b.withBase.length ? pct0(n / b.withBase.length) + " of outlets with a baseline" : "No baseline");
    const heroHtml = `<section class="panel"><div class="panel-head"><div><h2>Where the network is heading</h2><p>Month-end projection for ${int(list.length)} outlets, measured against ${esc(lm)} actual and the monthly target.</p></div>
      <div class="panel-tools">${dateControls(false)}<button class="btn" data-nreport>Regional head report</button></div></div>
      <div class="panel-body"><div class="kpis net-kpis">
      ${netHero({ label: "Projected this month", value: bdt(projTotal || null), title: exact(projTotal), sub: `${tchip(pjTone)} ${pct0(ach)} of monthly target`, ratio: ach, tone: pjTone, aria: `Projected ${pct0(ach)} of monthly target`, scale: "Monthly target",
        rows: [["Month on month", spct(b.growth), pn(b.growth)], [`Change vs ${lm}`, b.growth === null ? "—" : signed(b.change)], ["Gap to target", monthlyTarget ? signed(projTotal - monthlyTarget) : "—", projTotal - monthlyTarget >= 0 ? "pos" : "neg"]],
        foot: `<span>Growth measured on the ${int(b.withBase.length)} outlets with a ${esc(lm)} baseline</span>` })}
      ${kpi({ label: "Total target", value: bdt(monthlyTarget || null), sub: `${bdt(targetToDate || null)} due till date`, foot: "<span>Full-month target</span>", accent: "var(--line)" })}
      ${kpi({ label: "Actual till date", value: bdt(actualToDate || null), sub: tchip(tdTone, pct0(achToDate) + " · " + tdTone.label), foot: `<span>Gap ${targetToDate ? signed(actualToDate - targetToDate) : "—"}</span>`, accent: "var(--series-2)" })}
      ${kpi({ label: `${esc(lm)} sales`, value: bdt(b.lastTotal || null), sub: `${int(b.withBase.length)} of ${int(list.length)} outlets have a baseline`, foot: "<span>Full-month actual</span>", accent: "var(--series-3)" })}
      ${kpi({ label: "Daily run rate", value: bdt(runRate), sub: neededRate === null ? "Month complete" : `${bdt(neededRate)} a day needed to hit target`, foot: `<span>${int(observed.length)} trading days observed · ${int(remaining)} left</span>`, accent: "var(--series-4)" })}
      </div></div>
      <div class="stat-strip net-strip" style="border-top:1px solid var(--line-soft)">${[["Growing", growing, "good", "MoM above +2%", shareOf(growing)], ["Flat", flat, "warn", "MoM within ±2%", shareOf(flat)],
        ["Declining", declining, "bad", "MoM below −2%", shareOf(declining)], ["No baseline", list.length - b.withBase.length, "idle", `Not in ${lm} file`, "Left out of growth"]]
        .map(([l, n, k, rule, note]) => `<div><span><span class="chip ${k}">${esc(l)}</span> <span class="muted" style="font-weight:500">${esc(rule)}</span></span><strong>${int(n)}</strong><small>${esc(note)}</small></div>`).join("")}</div></section>`;

    // callouts
    const cards = [];
    const rho = netGroup(list, "regionalHead").filter((x) => x.lastMonth > 0).sort((x, y) => (y.delta || 0) - (x.delta || 0));
    const netGain = b.projOnBase - b.lastTotal;
    if (rho.length && (rho[0].delta || 0) > 0) {
      const top = rho[0];
      cards.push({ tone: "good", tag: "Leading", title: `${top.name} is adding the most`, body: `${bdt(top.delta)} more than ${lm} across ${int(top.outlets)} outlets, ${spct(top.mom)} growth.` + (netGain > 0 ? ` That is ${pct0(Math.min(1, top.delta / netGain))} of the network's net gain.` : "") });
    }
    if (rho.length > 1 && (rho[rho.length - 1].delta || 0) < 0) {
      const w = rho[rho.length - 1];
      cards.push({ tone: "bad", tag: "Drag", title: `${w.name} is the biggest drag`, body: `${bdt(w.delta)} against ${lm} (${spct(w.mom)}) across ${int(w.outlets)} outlets. Projected achievement is ${pct0(w.projectedAchievement)}.` });
    }
    const risk = list.filter((r) => nnum(r.momGrowth) !== null && r.momGrowth < -0.02 && nnum(r.projectedAchievement) !== null && r.projectedAchievement < 1);
    if (risk.length) cards.push({ tone: "bad", tag: "At risk", title: `${int(risk.length)} outlets are declining and behind target`, body: `Together they are ${bdt(risk.reduce((s, r) => s + Math.abs(nnum(r.projectedGap) || 0), 0))} short of their monthly target, the quickest place to recover the gap. Switch the quadrant to Outlet to find them.` });
    const ranked = list.slice().sort((x, y) => (nnum(y.projectedSales) || 0) - (nnum(x.projectedSales) || 0));
    if (ranked.length > 10 && projTotal) {
      const n = Math.max(1, Math.round(ranked.length * 0.1)), sh = ranked.slice(0, n).reduce((s, r) => s + (nnum(r.projectedSales) || 0), 0) / projTotal;
      cards.push({ tone: "info", tag: "Concentration", title: `The top 10% of outlets carry ${pct0(sh)} of projected sales`, body: `${int(n)} of ${int(ranked.length)} outlets. ${sh > 0.35 ? "Revenue is concentrated, so protect these first." : "Revenue is well spread across the estate."}` });
    }
    const wk = weekdayTotals(daily).filter((w) => w.days > 0);
    if (wk.length > 1) {
      const best = wk.slice().sort((x, y) => y.avg - x.avg)[0], avgAll = wk.reduce((s, w) => s + w.avg, 0) / wk.length;
      cards.push({ tone: "info", tag: "Rhythm", title: `${best.name} is the strongest trading day`, body: `${bdt(best.avg)} on an average ${best.name}, ${spct(best.avg / avgAll - 1)} against the average weekday. ${int(best.days)} such day${best.days === 1 ? "" : "s"} observed this month.` });
    }
    const thisYear = (S.net.month || "").slice(0, 4), cohort = list.filter((r) => (r.launchDate || "").slice(0, 4) === thisYear);
    if (cohort.length && projTotal) {
      const cp = cohort.reduce((s, r) => s + (nnum(r.projectedSales) || 0), 0);
      cards.push({ tone: "warn", tag: "New outlets", title: `${int(cohort.length)} outlets opened in ${thisYear} bring ${pct0(cp / projTotal)} of sales`, body: `${bdt(cp)} projected from the newest cohort: ${pct0(cohort.length / list.length)} of outlets.` });
    }
    if (monthlyTarget) {
      const gap = monthlyTarget - projTotal;
      cards.push({ tone: gap > 0 ? "warn" : "good", tag: "Target", title: gap > 0 ? `${bdt(gap)} short of the monthly target` : `Tracking ${bdt(-gap)} ahead of target`,
        body: remaining > 0 ? `${int(remaining)} days left. ${gap > 0 ? `Closing it needs an extra ${bdt(gap / remaining)} a day on top of the projection.` : "The current run rate is enough to finish ahead."}` : "The month is complete on the selected date." });
    }
    const callouts = `<section class="panel"><div class="panel-head"><div><h2>What the numbers are saying</h2><p>Written from the outlets in view; it changes as you filter.</p></div></div>
      <div class="panel-body"><div class="findings">${cards.map((c) => `<div class="finding" style="--sev:var(--${c.tone})"><div class="finding-bar"></div><div><h3><span class="chip ${c.tone}">${esc(c.tag)}</span> <span>${esc(c.title)}</span></h3><p>${esc(c.body)}</p></div></div>`).join("") || '<p class="net-empty">Not enough data in the current selection to write a read-out.</p>'}</div></div></section>`;

    // quadrant (drawn after the page is in the DOM, at its measured width)
    const quadGroups = netGroup(list, st.quad).filter((x) => x.lastMonth > 0 && x.monthlyTarget > 0).map((x) => ({ ...x, quad: quadOf(x.mom, x.projectedAchievement) }));
    NCSV.quad = () => [`momentum_quadrant_${st.quad}`, [NET_LEVELS[st.quad], "Quadrant", "Outlets", `${lm} sales`, "Projected month-end", "MoM change", "MoM growth", "Monthly target", "Projected achievement"],
      quadGroups.map((x) => [x.name, x.quad.label, x.outlets, rnd(x.lastMonth), rnd(x.projected), rnd(x.delta || 0), pcsv1(x.mom), rnd(x.monthlyTarget), pcsv1(x.projectedAchievement)])];
    const quad = `<section class="panel"><div class="panel-head"><div><h2>Momentum quadrant</h2><p>Month-on-month growth against projected target achievement. Marker shape names the quadrant; size is projected sales.</p></div>
      <div class="panel-tools">${nseg("gm.quad", GM_LEVELS, "Quadrant level")}${csvBtn("quad")}</div></div>
      <div class="panel-body"><div class="chart"><svg id="quadrantChart" role="img" aria-label="Momentum quadrant scatter plot"></svg></div><div class="quad-legend" id="quadrantLegend"></div><p class="chart-note" id="quadrantNote"></p></div></section>`;

    // movers
    const movers = netGroup(list, st.mover).filter((x) => x.lastMonth > 0 && x.delta !== null).sort((x, y) => (st.dir === "gain" ? y.delta - x.delta : x.delta - y.delta));
    const mShown = movers.slice(0, st.mover === "outlet" ? 40 : 30);
    NCSV.movers = () => [`top_movers_${st.mover}_${st.dir}`, [NET_LEVELS[st.mover], "Detail", "Outlets", `${lm} sales`, "Projected month-end", "MoM change", "MoM growth", "Projected achievement"],
      movers.map((x) => [x.name, x.sub, x.outlets, rnd(x.lastMonth), rnd(x.projected), rnd(x.delta || 0), pcsv1(x.mom), pcsv1(x.projectedAchievement)])];
    let moverBody = '<p class="net-empty">No group in view has a last-month baseline.</p>';
    if (mShown.length) {
      const maxAbs = Math.max(...mShown.map((x) => Math.abs(x.delta)), 1), mixed = mShown.some((x) => x.delta >= 0) && mShown.some((x) => x.delta < 0);
      const origin = mixed ? 50 : mShown[0].delta >= 0 ? 0 : 100, scale = mixed ? 50 : 100;
      moverBody = `<div class="rank-list scroll">${mShown.map((x) => {
        const w = Math.max(0.8, (Math.abs(x.delta) / maxAbs) * scale), left = x.delta >= 0 ? origin : origin - w;
        return `<div class="rank-row"${st.mover === "outlet" && x.code ? ` role="button" tabindex="0" data-noutlet="${esc(x.code)}"` : ""}>
          <div class="rank-name"><strong title="${esc(x.name)}">${esc(x.name)}</strong><span>${esc(x.sub)}</span></div>
          <div class="bar-track"><i class="bar-fill" style="left:${left.toFixed(1)}%;width:${w.toFixed(1)}%;background:var(${x.delta >= 0 ? "--good" : "--bad"})"></i>${mixed ? `<span class="bar-axis" style="left:${origin}%"></span>` : ""}</div>
          <div class="rank-value" title="${esc(exact(x.delta))}">${x.delta >= 0 ? "+" : "−"}${compact(Math.abs(x.delta))}</div>
          <div class="rank-value ${pn(x.delta)}">${spct(x.mom)}</div></div>`;
      }).join("")}</div>
      <p class="chart-note">Bar length is the taka change; the percentage is growth on the same group's last-month base.${st.mover === "outlet" ? " Click an outlet for its profile." : ""}${movers.length > mShown.length ? ` Showing the top ${int(mShown.length)} of ${int(movers.length)}; the CSV has all of them.` : ""}</p>`;
    }
    const moversHtml = `<section class="panel"><div class="panel-head"><div><h2>Top movers</h2><p>${st.dir === "gain" ? "Largest gains" : "Largest declines"} in projected monthly sales against ${esc(lm)}.</p></div>
      <div class="panel-tools">${nseg("gm.mover", GM_LEVELS, "Mover level")}${nseg("gm.dir", [["gain", "Gainers"], ["loss", "Decliners"]], "Direction")}${csvBtn("movers")}</div></div>
      <div class="panel-body">${moverBody}</div></section>`;

    // heatmap
    const P = palette(), seen = daily.filter((x) => x.observed && x.actual > 0), heatRows = [];
    let heatBody = '<p class="net-empty">No trading days observed in the current selection.</p>';
    if (seen.length) {
      const first = (new Date(daily[0].date + "T00:00:00Z").getUTCDay() + 1) % 7, weeks = [];
      daily.forEach((x) => { const wd = (new Date(x.date + "T00:00:00Z").getUTCDay() + 1) % 7, wi = Math.floor((first + x.day - 1) / 7); (weeks[wi] = weeks[wi] || Array(7).fill(null))[wd] = x; });
      const vals = seen.map((x) => x.actual), min = Math.min(...vals), max = Math.max(...vals);
      const step = (v) => (max === min ? 3 : Math.min(6, Math.max(0, Math.round(((v - min) / (max - min)) * 6))));
      const body = weeks.filter(Boolean).map((week) => {
        const ds = week.filter(Boolean), label = `${ds[0].day}–${ds[ds.length - 1].day}`;
        return `<div class="heat-row"><div class="heat-label">${label}</div>${week.map((x, wd) => {
          if (!x) return '<div class="heat-cell outside" aria-hidden="true"></div>';
          heatRows.push([x.date, WEEKDAYS[wd], label, rnd(x.actual), rnd(x.target), x.target ? pcsv1(x.actual / x.target) : "", x.observed ? "yes" : "no"]);
          if (!x.observed || x.actual <= 0) return `<div class="heat-cell pending" title="${esc(fdate(x.date))}: not traded yet · target ${esc(bdt(x.target || null))}"></div>`;
          const hex = P(SEQ[step(x.actual)]), vs = x.target ? x.actual / x.target : null;
          return `<div class="heat-cell" style="background:${hex};color:${readableInk(hex)}" title="${esc(fdate(x.date))} · ${esc(bdt(x.actual))} · ${vs === null ? "no target" : pct0(vs) + " of target"}">${esc(compact(x.actual))}</div>`;
        }).join("")}</div>`;
      }).join("");
      const wks = weekdayTotals(daily).filter((w) => w.days), best = wks.slice().sort((x, y) => y.avg - x.avg)[0], worst = wks.slice().sort((x, y) => x.avg - y.avg)[0];
      heatBody = `<div class="heatmap"><div class="heat-row"><div class="heat-head">Days</div>${WEEKDAYS.map((w) => `<div class="heat-head">${w}</div>`).join("")}</div>${body}
        <div class="heat-scale"><span>${esc(bdt(min))}</span><i>${SEQ.map((s) => `<b style="background:var(${s})"></b>`).join("")}</i><span>${esc(bdt(max))}</span><span style="margin-left:auto;display:inline-flex;align-items:center;gap:6px"><span class="heat-cell pending" style="width:18px;height:12px;display:inline-block"></span>Not traded yet</span></div></div>
        ${best && worst && best !== worst ? `<p class="chart-note">Best average day ${best.name} (${esc(bdt(best.avg))}), weakest ${worst.name} (${esc(bdt(worst.avg))}).</p>` : ""}`;
    }
    NCSV.heat = () => ["trading_day_heatmap", ["Date", "Weekday", "Week", "Sales", "Target", "Achievement", "Observed"], heatRows];
    const heat = `<section class="panel"><div class="panel-head"><div><h2>Trading-day heatmap</h2><p>Network sales by week and weekday · ${esc(fmonth(S.net.month))}</p></div><div class="panel-tools">${csvBtn("heat")}</div></div>
      <div class="panel-body">${heatBody}</div></section>`;

    const traj = `<section class="panel"><div class="panel-head"><div><h2>Month trajectory</h2><p>Cumulative sales against cumulative target · ${esc(fmonth(S.net.month))}</p></div><div class="panel-tools">${csvBtn("traj")}</div></div>
      <div class="panel-body"><div class="chart-legend"><span><i class="swatch" style="background:var(--series-2)"></i>Actual to date</span><span><i class="swatch dash-1"></i>Projected finish</span><span><i class="swatch dash"></i>Cumulative target</span></div>
      <div class="chart"><svg id="trajectoryChart" role="img" aria-label="Cumulative sales against target across the month"></svg></div><p class="chart-note" id="trajectoryNote"></p></div></section>`;

    // league table
    const lg = st.league, gmd = gdrill("gm-league", lg), lgName = gmd ? "Outlet" : NET_LEVELS[lg];
    const league = mountTable("gm-league", {
      title: gmd ? `Outlets of ${gmd.key}` : `${lgName} league table`, file: gmd ? `outlets_${gmd.key}` : `${lg}_league_table`, stamp: S.netTo,
      desc: (n) => (gmd ? `${int(n)} outlets. Click an outlet for its profile.` : `${int(n)} ${lgName.toLowerCase()} groups. Click a row to list its outlets; click a heading to sort. The CSV has every column.`),
      rows: gmd ? netGroup(list.filter((r) => disp(r[netKey(lg)]) === gmd.key), "outlet") : netGroup(list, lg), key: (x) => x.name, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "projected", pageSize: 50,
      banner: gBanner("gm-league", gmd),
      rowAttr: (x) => (x.code ? `data-noutlet="${esc(x.code)}" tabindex="0"` : `data-gpick="gm-league" data-glevel="${esc(lg)}" data-gkey="${esc(x.name)}" tabindex="0" title="List ${esc(x.name)}'s outlets"`),
      tools: nseg("gm.league", [["regionalHead", "Regional head"], ["zonal", "Zonal"], ["division", "Division"], ["format", "Format"]], "League level"),
      cols: [
        { k: "name", label: lgName, fmt: (x) => `<span class="cell-primary" title="${esc(x.sub)}">${esc(x.name)}</span>`, csv: (x) => x.name },
        { k: "outlets", label: "Outlets", num: 1, fmt: (x) => int(x.outlets) },
        { k: "lastMonth", label: lm, num: 1, fmt: (x) => bdt(x.lastMonth || null), csv: (x) => rnd(x.lastMonth) },
        { k: "actual", label: "Actual (TD)", num: 1, fmt: (x) => bdt(x.actual), csv: (x) => rnd(x.actual) },
        { k: "target", label: "Target (TD)", num: 1, fmt: (x) => bdt(x.target), csv: (x) => rnd(x.target) },
        { k: "achievement", label: "Ach. (TD)", num: 1, fmt: (x) => ratePair(x.achievement), csv: (x) => pcsv1(x.achievement) },
        { k: "monthlyTarget", label: "Monthly target", num: 1, fmt: (x) => bdt(x.monthlyTarget), csv: (x) => rnd(x.monthlyTarget) },
        { k: "projected", label: "Projected", num: 1, fmt: (x) => bdt(x.projected), csv: (x) => rnd(x.projected) },
        { k: "projectedAchievement", label: "Projected ach.", num: 1, fmt: (x) => ratePair(x.projectedAchievement), csv: (x) => pcsv1(x.projectedAchievement) },
        { k: "delta", label: "MoM change", num: 1, fmt: (x) => `<span class="${pn(x.delta)}" title="${esc(exact(x.delta))}">${signed(x.delta)}</span>`, csv: (x) => rnd(x.delta) },
        { k: "mom", label: "MoM growth", num: 1, fmt: (x) => `<span class="${pn(x.mom)}">${spct(x.mom)}</span>`, csv: (x) => pcsv1(x.mom) },
      ],
    });

    AFTER.push(() => drawGmCharts(list, quadGroups, daily));
    return `${heroHtml}${callouts}${quad}<div class="grid-h">${moversHtml}${heat}</div>${traj}${league}`;
  }

  let gmChartWidth = 0;
  function drawGmCharts(list, quadGroups, daily) {
    const svg = $("#quadrantChart");
    if (!svg) return;
    gmChartWidth = svg.parentElement.clientWidth;
    drawQuadrant(svg, quadGroups);
    drawTrajectory($("#trajectoryChart"), list, daily);
  }
  function drawQuadrant(svg, groups) {
    const P = palette(), lm = netLM(), isOutlet = S.gm.quad === "outlet";
    svg.replaceChildren();
    const W = Math.max(280, Math.round(svg.parentElement.clientWidth)), H = W < 520 ? 340 : 420, pad = { t: 24, r: 22, b: 48, l: 60 };
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H); svg.style.height = H + "px";
    const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    const legend = $("#quadrantLegend"), note = $("#quadrantNote");
    if (!groups.length) {
      const t = svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: P("--viz-muted"), "font-size": 14 });
      t.textContent = "No group in the current selection has both a last-month baseline and a monthly target.";
      svg.append(t); legend.replaceChildren(); note.textContent = "";
      return;
    }
    // Robust domain: the span is the 90th percentile of |value|, so one runaway outlier can't squash
    // everyone into the centre. Outliers clamp to the edge.
    const span = (vals, floor) => {
      const abs = vals.map(Math.abs).filter(isFinite).sort((x, y) => x - y);
      return abs.length ? Math.max(floor, Math.ceil(abs[Math.min(abs.length - 1, Math.floor(abs.length * 0.9))] * 1.15 * 100) / 100) : floor;
    };
    const gS = span(groups.map((x) => x.mom), 0.1), aS = span(groups.map((x) => x.projectedAchievement - 1), 0.08);
    const clamped = groups.filter((x) => Math.abs(x.mom) > gS || Math.abs(x.projectedAchievement - 1) > aS).length;
    const X = (v) => pad.l + ((Math.max(-gS, Math.min(gS, v)) + gS) / (2 * gS)) * plotW;
    const Y = (v) => pad.t + plotH - ((Math.max(-aS, Math.min(aS, v - 1)) + aS) / (2 * aS)) * plotH;
    const cx = X(0), cy = Y(1);
    [{ q: QUADS.holding, x: pad.l, y: pad.t, w: cx - pad.l, h: cy - pad.t }, { q: QUADS.accelerating, x: cx, y: pad.t, w: pad.l + plotW - cx, h: cy - pad.t },
      { q: QUADS.atrisk, x: pad.l, y: cy, w: cx - pad.l, h: pad.t + plotH - cy }, { q: QUADS.catching, x: cx, y: cy, w: pad.l + plotW - cx, h: pad.t + plotH - cy }].forEach((w) => {
      if (w.w <= 0 || w.h <= 0) return;
      svg.append(svgEl("rect", { x: w.x, y: w.y, width: w.w, height: w.h, fill: P(w.q.color), opacity: 0.06 }));
      const l = svgEl("text", { x: w.x + w.w / 2, y: w.y + w.h / 2, "text-anchor": "middle", "dominant-baseline": "middle", fill: P("--viz-muted"), "font-size": W < 520 ? 12 : 16, "font-weight": 620, opacity: 0.55, "pointer-events": "none" });
      l.textContent = `${w.q.glyph} ${w.q.label}`;
      svg.append(l);
    });
    svg.append(svgEl("rect", { x: pad.l, y: pad.t, width: plotW, height: plotH, fill: "none", stroke: P("--viz-grid") }));
    svg.append(svgEl("line", { x1: cx, y1: pad.t, x2: cx, y2: pad.t + plotH, stroke: P("--viz-axis"), "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    svg.append(svgEl("line", { x1: pad.l, y1: cy, x2: pad.l + plotW, y2: cy, stroke: P("--viz-axis"), "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    const tick = (tx, ty, label, anchor) => { const t = svgEl("text", { x: tx, y: ty, "text-anchor": anchor, fill: P("--viz-muted"), "font-size": 11 }); t.textContent = label; svg.append(t); };
    [-gS, -gS / 2, 0, gS / 2, gS].forEach((v) => tick(X(v), pad.t + plotH + 18, spct(v, 0), "middle"));
    [1 - aS, 1 - aS / 2, 1, 1 + aS / 2, 1 + aS].forEach((v) => tick(pad.l - 10, Y(v) + 4, npct(v), "end"));
    const xt = svgEl("text", { x: pad.l + plotW / 2, y: H - 8, "text-anchor": "middle", fill: P("--viz-muted"), "font-size": 11.5, "font-weight": 600 });
    xt.textContent = `Month-on-month growth vs ${lm} →`; svg.append(xt);
    const yt = svgEl("text", { x: 16, y: pad.t + plotH / 2, "text-anchor": "middle", fill: P("--viz-muted"), "font-size": 11.5, "font-weight": 600, transform: `rotate(-90 16 ${pad.t + plotH / 2})` });
    yt.textContent = "Projected target achievement →"; svg.append(yt);
    // shape carries the quadrant, colour is the second cue
    const maxProj = Math.max(...groups.map((x) => x.projected), 1);
    const shape = (q, px, py, r) => {
      if (q.key === "holding") return svgEl("circle", { cx: px, cy: py, r });
      if (q.key === "catching") return svgEl("polygon", { points: `${px},${py - r} ${px + r},${py} ${px},${py + r} ${px - r},${py}` });
      const dir = q.key === "accelerating" ? -1 : 1;
      return svgEl("polygon", { points: `${px},${py + dir * r} ${px + r},${py - dir * r * 0.8} ${px - r},${py - dir * r * 0.8}` });
    };
    const sorted = groups.slice().sort((x, y) => y.projected - x.projected);
    const labelled = new Set(sorted.slice(0, isOutlet ? 0 : W < 520 ? 3 : 8).map((x) => x.name)), placed = [];
    sorted.forEach((gr) => {
      const r = isOutlet ? 3 + Math.sqrt(gr.projected / maxProj) * 6 : 7 + Math.sqrt(gr.projected / maxProj) * 15, px = X(gr.mom), py = Y(gr.projectedAchievement);
      const node = shape(gr.quad, px, py, r);
      node.setAttribute("fill", P(gr.quad.color)); node.setAttribute("fill-opacity", isOutlet ? 0.62 : 0.85);
      node.setAttribute("stroke", P("--viz-surface")); node.setAttribute("stroke-width", 2);
      if (isOutlet && gr.code) { node.style.cursor = "pointer"; node.addEventListener("click", () => { hideTip(); openNetOutlet(gr.code); }); }
      attachTip(node, () => `<strong>${esc(gr.name)}</strong><dl><dt>${esc(gr.quad.glyph + " " + gr.quad.label)}</dt><dd>${esc(gr.sub || "")}</dd>
        <dt>${esc(lm)}</dt><dd>${bdt(gr.lastMonth)}</dd><dt>Projected</dt><dd>${bdt(gr.projected)}</dd><dt>MoM growth</dt><dd>${spct(gr.mom)}</dd>
        <dt>Monthly target</dt><dd>${bdt(gr.monthlyTarget)}</dd><dt>Projected ach.</dt><dd>${npct(gr.projectedAchievement)}</dd></dl>`);
      svg.append(node);
      // Direct-label the biggest groups, skipping any label that would collide with one already placed.
      if (labelled.has(gr.name)) {
        const short = gr.name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter((w) => !/^(mr|md|mrs|ms)\.?$/i.test(w)).slice(0, 2).join(" ");
        const ly = py - r - 6;
        if (!placed.some((p) => Math.abs(p.x - px) < 78 && Math.abs(p.y - ly) < 15)) {
          const at = { x: px, y: ly, "text-anchor": "middle", "font-size": 11, "font-weight": 650, "pointer-events": "none" };
          const halo = svgEl("text", { ...at, fill: P("--viz-surface"), stroke: P("--viz-surface"), "stroke-width": 4, "stroke-linejoin": "round" }), lab = svgEl("text", { ...at, fill: P("--viz-ink") });
          halo.textContent = short; lab.textContent = short;
          svg.append(halo, lab); placed.push({ x: px, y: ly });
        }
      }
    });
    legend.innerHTML = Object.values(QUADS).map((q) => {
      const m = groups.filter((x) => x.quad.key === q.key);
      return `<div class="quad-item"><span class="glyph" style="color:${P(q.color)}" aria-hidden="true">${q.glyph}</span><div><strong>${q.label} · ${int(m.length)}</strong><small>${q.note} · ${bdt(m.reduce((s, x) => s + x.projected, 0))} projected</small></div></div>`;
    }).join("");
    note.textContent = `${int(groups.length)} ${NET_LEVELS[S.gm.quad].toLowerCase()} group${groups.length === 1 ? "" : "s"} plotted; marker area is projected month-end sales. `
      + `Axes are scaled to the bulk of the data (±${spct(gS, 0).replace("+", "")} growth, ${npct(1 - aS)}–${npct(1 + aS)} achievement)`
      + (clamped ? `; ${int(clamped)} beyond that sit pinned on the edge. Hover for the true value.` : ".");
  }
  function drawTrajectory(svg, list, daily) {
    if (!svg) return;
    const P = palette();
    svg.replaceChildren();
    NCSV.traj = () => ["month_trajectory", ["Date", "Day", "Daily sales", "Daily target", "Cumulative sales", "Cumulative projected", "Cumulative target"], []];
    if (!daily.length) return;
    const W = Math.max(280, Math.round(svg.parentElement.clientWidth)), H = Math.max(240, Math.min(340, W * (W < 520 ? 0.75 : 0.34))), pad = { t: 18, r: W < 520 ? 68 : 96, b: 40, l: 54 };
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H); svg.style.height = H + "px";
    const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    let ca = 0, ct = 0;
    const series = daily.map((x) => { if (x.observed) ca += x.actual; ct += x.target; return { ...x, cumActual: x.observed && x.actual > 0 ? ca : null, cumTarget: ct }; });
    const obs = series.filter((s) => s.cumActual !== null), last = obs[obs.length - 1];
    const projectedTotal = nsum(list, "projectedSales"), observedTotal = last ? last.cumActual : 0;
    const rest = series.filter((s) => last && s.day > last.day), restTarget = rest.reduce((s, x) => s + x.target, 0);
    let accum = observedTotal;
    // Spread the projected remainder across the remaining days in proportion to their target weight.
    const proj = rest.map((x) => { accum += (projectedTotal - observedTotal) * (restTarget ? x.target / restTarget : 1 / rest.length); return { day: x.day, value: accum }; });
    const rawMax = Math.max(ct, projectedTotal, observedTotal, 1) * 1.04, mag = Math.pow(10, Math.floor(Math.log10(rawMax / 4))), step = Math.ceil(rawMax / 4 / mag) * mag, maxY = step * 4;
    const X = (day) => pad.l + ((day - 1) / Math.max(1, daily.length - 1)) * plotW, Y = (v) => pad.t + plotH - (v / maxY) * plotH;
    for (let i = 0; i <= 4; i++) {
      const gy = Y(step * i);
      svg.append(svgEl("line", { x1: pad.l, y1: gy, x2: pad.l + plotW, y2: gy, stroke: P("--viz-grid") }));
      const t = svgEl("text", { x: pad.l - 10, y: gy + 4, "text-anchor": "end", fill: P("--viz-muted"), "font-size": 10.5 }); t.textContent = compact(step * i); svg.append(t);
    }
    daily.forEach((x) => {
      if (x.day !== 1 && x.day !== daily.length && x.day % (W < 520 ? 10 : 5) !== 0) return;
      const t = svgEl("text", { x: X(x.day), y: pad.t + plotH + 18, "text-anchor": "middle", fill: P("--viz-muted"), "font-size": 10.5 }); t.textContent = String(x.day); svg.append(t);
    });
    svg.append(svgEl("line", { x1: pad.l, y1: pad.t + plotH, x2: pad.l + plotW, y2: pad.t + plotH, stroke: P("--viz-axis") }));
    const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p.day).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ");
    svg.append(svgEl("path", { d: path(series.map((s) => ({ day: s.day, value: s.cumTarget }))), fill: "none", stroke: P("--viz-axis"), "stroke-width": 2, "stroke-dasharray": "6 5", "stroke-linecap": "round" }));
    if (obs.length) svg.append(svgEl("path", { d: path(obs.map((s) => ({ day: s.day, value: s.cumActual }))), fill: "none", stroke: P("--series-2"), "stroke-width": 2.5, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    if (proj.length && last) svg.append(svgEl("path", { d: path([{ day: last.day, value: observedTotal }].concat(proj)), fill: "none", stroke: P("--series-2"), "stroke-width": 2.5, "stroke-dasharray": "7 6", "stroke-linecap": "round", opacity: 0.75 }));
    const endLabel = (value, text, color, dy) => {
      const ly = Math.max(pad.t + 10, Math.min(pad.t + plotH, Y(value) + dy));
      const t1 = svgEl("text", { x: pad.l + plotW + 8, y: ly - 4, fill: color, "font-size": 10.5, "font-weight": 800 }), t2 = svgEl("text", { x: pad.l + plotW + 8, y: ly + 9, fill: P("--viz-muted"), "font-size": 10.5 });
      t1.textContent = text; t2.textContent = compact(value); svg.append(t1, t2);
    };
    endLabel(ct, "Target", P("--viz-muted"), ct >= projectedTotal ? -8 : 12);
    endLabel(projectedTotal, "Projected", P("--series-2"), ct >= projectedTotal ? 14 : -6);
    if (last) {
      svg.append(svgEl("line", { x1: X(last.day), y1: pad.t, x2: X(last.day), y2: pad.t + plotH, stroke: P("--viz-axis"), "stroke-dasharray": "3 4" }));
      svg.append(svgEl("circle", { cx: X(last.day), cy: Y(observedTotal), r: 4.5, fill: P("--series-2"), stroke: P("--viz-surface"), "stroke-width": 2 }));
    }
    const hover = svgEl("line", { y1: pad.t, y2: pad.t + plotH, stroke: P("--accent"), opacity: 0 }), cap = svgEl("rect", { x: pad.l, y: pad.t, width: plotW, height: plotH, fill: "transparent" });
    svg.append(hover, cap);
    const projByDay = new Map(proj.map((p) => [p.day, p.value]));
    cap.addEventListener("pointermove", (e) => {
      const box = svg.getBoundingClientRect(), px = ((e.clientX - box.left) / box.width) * W, day = Math.round(((px - pad.l) / plotW) * (daily.length - 1)) + 1, s = series.find((v) => v.day === day);
      if (!s) return;
      hover.setAttribute("x1", X(day)); hover.setAttribute("x2", X(day)); hover.setAttribute("opacity", 1);
      const cum = s.cumActual !== null ? s.cumActual : projByDay.get(day);
      showTip(e, `<strong>${fdate(s.date)} · day ${day}</strong><dl><dt>${s.cumActual === null ? "Projected cumulative" : "Cumulative sales"}</dt><dd>${bdt(cum)}</dd>
        <dt>Cumulative target</dt><dd>${bdt(s.cumTarget)}</dd><dt>Variance</dt><dd>${cum == null ? "—" : bdt(cum - s.cumTarget)}</dd><dt>Day sales</dt><dd>${s.observed && s.actual ? bdt(s.actual) : "—"}</dd></dl>`);
    });
    cap.addEventListener("pointerleave", () => { hover.setAttribute("opacity", 0); hideTip(); });
    NCSV.traj = () => ["month_trajectory", ["Date", "Day", "Daily sales", "Daily target", "Cumulative sales", "Cumulative projected", "Cumulative target"],
      series.map((s) => [s.date, s.day, s.observed ? rnd(s.actual) : "", rnd(s.target), rnd(s.cumActual), rnd(s.cumActual !== null ? s.cumActual : projByDay.get(s.day)), rnd(s.cumTarget)])];
    const variance = observedTotal - (last ? last.cumTarget : 0);
    $("#trajectoryNote").textContent = last ? `Through ${fdate(last.date)} the network is ${bdt(Math.abs(variance))} ${variance >= 0 ? "ahead of" : "behind"} the cumulative target. The dashed tail spreads the remaining projection across the ${int(proj.length)} unfinished days in proportion to their daily target.` : "";
  }

  // ---- outlet profile drawer (both network pages)
  function openNetOutlet(code) {
    const pool = inView(), row = pool.find((r) => r.code === code) || baseList().find((r) => r.code === code);
    if (!row) return;
    const lm = netLM(), tdT = perfTone(row.salesAchievement), pjT = perfTone(row.projectedAchievement), gT = growthTone(row.momGrowth);
    const rh = disp(row.regionalHead) !== "—" ? "regionalHead" : "leader";
    const rank = (list) => {
      const ranked = list.filter((r) => isNum(r.projectedAchievement)).sort((x, y) => y.projectedAchievement - x.projectedAchievement), i = ranked.findIndex((r) => r.code === row.code);
      return i < 0 ? "—" : `${int(i + 1)} of ${int(ranked.length)}`;
    };
    const meter = (label, value, ratio, tone) => {
      const sm = Math.max(1.2, isNum(ratio) ? Math.min(ratio, 2) : 0), fill = isNum(ratio) ? (Math.min(ratio, sm) / sm) * 100 : 0;
      return `<div><div class="hero-row"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>
        <div class="meter" role="img" aria-label="${esc(label)} ${pct0(ratio)}"><i class="${isNum(ratio) ? tone.key : ""}" style="width:${fill.toFixed(1)}%"></i><b style="left:${(100 / sm).toFixed(1)}%" title="Target"></b></div>
        <div class="meter-scale"><span>0%</span><span>Target 100%</span></div></div>`;
    };
    const person = (role, name, id, phone) => {
      if (disp(name) === "—") return "";
      const tel = String(phone || "").replace(/[^\d+]/g, "");
      return `<div class="person"><span>${esc(role)}${id ? " · ID " + esc(id) : ""}</span><strong>${esc(name)}</strong>${tel ? `<a href="tel:${esc(tel)}">${esc(phone)}</a>` : ""}</div>`;
    };
    const attrs = [["Format", row.format], ["Store status", row.status], ["PNP status", row.pnpStatus], ["Division", row.division], ["District", row.district], ["Area", row.area],
      ["Location type", row.locationType], ["Dv / Ds / T", row.cityType], ["Density", row.density], ["Income level", row.incomeLevel], ["Floor type", row.floorType], ["Layout shape", row.layoutShape],
      ["Floor area", nnum(row.sft) ? int(row.sft) + " sft" : null], ["Launched", row.launchDate ? fdate(row.launchDate) : null]].filter(([, v]) => disp(v) !== "—");
    const geo = String(row.geoLocation || "");
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = `${disp(row.code)} · ${disp(row.outletName)}`;
    $("#drawerBody").innerHTML = `
      <p class="muted" style="margin:0">${esc([disp(row.format), [disp(row.district), disp(row.division)].filter((s) => s !== "—").join(", "), disp(row.area)].filter((s) => s && s !== "—").join(" · "))}</p>
      <div class="stat-grid three">
        <div class="stat"><small>Actual till date</small><strong>${bdt(row.salesToDate)}</strong><small>Target ${bdt(row.targetToDate)}</small><div>${tchip(tdT, pct0(row.salesAchievement) + " · " + tdT.label)}</div></div>
        <div class="stat"><small>Projected month-end</small><strong>${bdt(row.projectedSales)}</strong><small>Monthly target ${bdt(row.monthlyTarget)}</small><div>${tchip(pjT, pct0(row.projectedAchievement) + " · " + pjT.label)}</div></div>
        <div class="stat"><small>${esc(lm)} sales</small><strong>${bdt(row.lastMonthSales)}</strong><small>${nnum(row.lastMonthSales) === null ? "No baseline for this outlet" : "Change " + bdt(row.projectedVsLastMonth)}</small><div>${tchip(gT, nnum(row.momGrowth) === null ? "No base" : spct(row.momGrowth) + " · " + gT.label)}</div></div>
      </div>
      <div><div class="section-title">Against target</div><dl style="margin:0;display:grid;gap:14px">
        ${meter("Till date", `${bdt(row.salesToDate)} of ${bdt(row.targetToDate)} · ${pct0(row.salesAchievement)}`, row.salesAchievement, tdT)}
        ${meter("Projected month-end", `${bdt(row.projectedSales)} of ${bdt(row.monthlyTarget)} · ${pct0(row.projectedAchievement)}`, row.projectedAchievement, pjT)}</dl></div>
      <div><div class="section-title">Daily sales against daily target · ${esc(fmonth(S.net.month))}</div>
        <div class="chart-legend"><span><i class="swatch" style="background:var(--good)"></i>At or above target</span><span><i class="swatch" style="background:var(--bad)"></i>Below target</span><span><i class="swatch" style="background:var(--ink-2)"></i>Daily target</span></div>
        <div id="profileDaily" class="chart"></div></div>
      <div><div class="section-title">Rank by projected achievement, best first</div>
        <table class="compact"><thead><tr><th>Within</th><th class="num">Rank</th></tr></thead><tbody>
        <tr><td>All outlets in view</td><td class="num">${rank(pool)}</td></tr>
        <tr><td>${esc(disp(row[rh]))}'s portfolio</td><td class="num">${rank(pool.filter((r) => disp(r[rh]) === disp(row[rh])))}</td></tr>
        <tr><td>${esc(disp(row.zonal))}'s zone</td><td class="num">${rank(pool.filter((r) => disp(r.zonal) === disp(row.zonal)))}</td></tr>
        <tr><td>${esc(disp(row.format))} outlets</td><td class="num">${rank(pool.filter((r) => disp(r.format) === disp(row.format)))}</td></tr></tbody></table></div>
      <div><div class="section-title">People</div><div class="people">${person("Regional head", disp(row.regionalHead) !== "—" ? row.regionalHead : row.leader, row.rhoId, row.rhoPhone)}${person("Zonal", row.zonal, row.zonalId, row.zonalPhone)}</div></div>
      <div><div class="section-title">Outlet details</div><dl class="kv">${attrs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(disp(v))}</dd>`).join("")}
        ${/^https?:\/\//i.test(geo) ? `<dt>Map</dt><dd><a href="${esc(geo)}" target="_blank" rel="noopener">Open location ↗</a></dd>` : ""}</dl></div>`;
    showDrawer();
    requestAnimationFrame(() => drawDaily(row));
  }
  function drawDaily(row) {
    const host = $("#profileDaily");
    if (!host) return;
    const month = S.net.month, days = monthDays(month + "-01"), t = row.dailySalesTargets || {}, a = row.dailySalesActuals || {}, series = [];
    for (let dd = 1; dd <= days; dd++) { const iso = `${month}-${String(dd).padStart(2, "0")}`; series.push({ d: dd, iso, target: nnum(t[iso]), actual: iso <= (S.netTo || "") ? nnum(a[iso]) : null }); }
    if (!series.some((s) => s.target || s.actual)) { host.innerHTML = '<p class="net-empty">No daily target or sales for this outlet.</p>'; return; }
    const max = Math.max(1, ...series.map((s) => Math.max(s.target || 0, s.actual || 0))) * 1.1, P = palette();
    const W = Math.max(280, Math.round(host.clientWidth || 480)), H = 150, pad = { t: 8, r: 4, b: 22, l: 44 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b, slot = pw / days, bw = Math.max(3, slot * 0.62), yv = (v) => pad.t + ph - (v / max) * ph;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Daily sales against daily target" });
    [0, 0.5, 1].forEach((f) => {
      const v = (max / 1.1) * f, gy = yv(v);
      svg.append(svgEl("line", { x1: pad.l, x2: W - pad.r, y1: gy, y2: gy, stroke: P("--grid") }));
      const l = svgEl("text", { x: pad.l - 6, y: gy + 3.5, "text-anchor": "end", fill: P("--ink-3"), "font-size": 10.5 }); l.textContent = compact(v); svg.append(l);
    });
    series.forEach((s) => {
      const x = pad.l + (s.d - 1) * slot + (slot - bw) / 2;
      if (s.actual != null) {
        const r = svgEl("rect", { x, y: yv(s.actual), width: bw, height: Math.max(1, pad.t + ph - yv(s.actual)), rx: 1.5, fill: !s.target || s.actual >= s.target ? P("--good") : P("--bad") });
        const tt = svgEl("title"); tt.textContent = `${fdate(s.iso)} · sales ${bdt(s.actual)} · target ${bdt(s.target)}`; r.append(tt); svg.append(r);
      }
      if (s.target) svg.append(svgEl("line", { x1: x - 1, x2: x + bw + 1, y1: yv(s.target), y2: yv(s.target), stroke: P("--ink-2"), "stroke-width": 1.6 }));
      if (s.d === 1 || s.d === days || s.d % 5 === 0) {
        const l = svgEl("text", { x: x + bw / 2, y: H - 6, "text-anchor": s.d === 1 ? "start" : s.d === days ? "end" : "middle", fill: P("--ink-3"), "font-size": 10.5 }); l.textContent = String(s.d); svg.append(l);
      }
    });
    host.replaceChildren(svg);
  }

  // ---- Regional head summary report: A4 landscape, print to PDF or download PNG. Built from whatever
  // is filtered, on a fixed print palette (assets/report.css) so it looks the same from either theme.
  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
  function rpTile(label, value, note, tone) {
    const d = el("div", "rp-tile" + (tone ? " " + tone : "")), dd = el("dd", tone === "pos" || tone === "neg" ? tone : null, value);
    d.append(el("dt", null, label), dd);
    if (note) dd.append(el("small", null, note));
    return d;
  }
  function rpMeter(label, value, ratio, tone) {
    const w = el("div", "rp-meter-row"), bar = el("div", "rp-meter"), fill = el("i", tone);
    w.append(el("span", "lbl", label), el("span", "val", value));
    fill.style.width = Math.max(0, Math.min(100, (ratio || 0) * 100)) + "%";
    bar.append(fill);
    if (ratio != null) { const m = el("span", "mark"); m.style.left = "100%"; bar.append(m); }
    w.append(bar);
    return w;
  }
  function rpTable(headers, rows) {
    const t = el("table", "rp-table"), hr = el("tr"), tb = el("tbody"), th = el("thead");
    headers.forEach((h) => hr.append(el("th", h.c ? "c" : null, h.label ?? h)));
    th.append(hr);
    rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((c) => { const td = el("td", c && c.cls ? c.cls : null); if (c && c.html) td.innerHTML = c.html; else td.textContent = c && c.text !== undefined ? c.text : c; if (c && c.title) td.title = c.title; tr.append(td); });
      tb.append(tr);
    });
    t.append(th, tb);
    return t;
  }
  // Achievement is a three-state judgement, not pass/fail: 96% must not print like a failure.
  const achCls = (v) => { const k = perfTone(v).key; return k === "good" ? "pos" : k === "warn" ? "warn" : "neg"; };
  const tileTone = (v) => (achCls(v) === "warn" ? "neu" : achCls(v));
  function buildReport(list) {
    const sheet = $("#reportSheet"), lm = netLM(), rm = S.net.month;
    sheet.replaceChildren();
    const groups = netGroup(list, "regionalHead", true).map((x) => ({ ...x, quad: quadOf(x.mom ?? 0, x.projectedAchievement ?? 0) })).sort((x, y) => y.projected - x.projected);
    const generated = new Date().toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    const active = dims().filter(([k]) => S.filters[k].size).map(([k, label]) => `${label}: ${[...S.filters[k]].join(", ")}`);
    const filterText = active.length ? active.join(" · ") : "None, full network";
    // Page numbers are stamped at the end, once the page count is known.
    const foot = () => { const f = el("div", "rp-foot"); f.append(el("span", null, `Operations Dashboard · Growth & momentum · Generated ${generated}`), el("span", "rp-pageno")); return f; };
    const topline = (right) => { const t = el("div", "rp-topline"), l = el("span"); l.append(el("b", null, "OUTLET NETWORK"), document.createTextNode("  ·  Growth & momentum")); t.append(l, el("span", null, right)); return t; };
    const oname = (r) => outletLabel(r);

    const p1 = el("section", "report-page"), hero = el("div", "rp-hero"), meta = el("div", "meta");
    hero.append(el("p", "kicker", "Regional Head Summary Report"), el("h1", null, "Growth & momentum"), el("h2", null, `${fmonth(rm)} · sales through ${fdate(S.netTo)}`));
    [["Outlets", int(list.length)], ["Regional heads", int(groups.length)], ["Baseline", lm], ["Generated", generated], ["Filters", filterText]].forEach(([k, v]) => { const s = el("span"); s.append(document.createTextNode(k + " "), el("b", null, v)); meta.append(s); });
    hero.append(meta); p1.append(hero);
    const tt = nsum(list, "monthlyTarget"), td = nsum(list, "targetToDate"), ad = nsum(list, "salesToDate"), pj = nsum(list, "projectedSales"), b = baseTotals(list);
    const projAch = tt ? pj / tt : null, tdAch = td ? ad / td : null;
    const s1 = el("section", "rp-section"), h1 = el("h3", "rp-h", "Network position"), tiles = el("div", "rp-tiles six");
    h1.append(el("span", null, "Projection model: observed Friday / Saturday / Sun–Thu run rates"));
    tiles.append(rpTile("Total target", bdt(tt), `${bdt(td)} due till date`), rpTile("Total actual (TD)", bdt(ad), `${npct(tdAch)} of till-date target`, tdAch >= 1 ? "pos" : "neg"),
      rpTile(lm, bdt(b.lastTotal), `${int(b.withBase.length)} outlets with a base`), rpTile("Projected month-end", bdt(pj), `${bdt(pj - tt)} vs target`, pj >= tt ? "pos" : "neg"),
      rpTile("MoM growth", spct(b.growth), `${bdt(b.projOnBase - b.lastTotal)} change`, b.growth >= 0 ? "pos" : "neg"), rpTile("Projected achievement", npct(projAch), perfTone(projAch).label, tileTone(projAch)));
    s1.append(h1, tiles); p1.append(s1);
    const s2 = el("section", "rp-section"), h2 = el("h3", "rp-h", "Regional head ranking");
    h2.append(el("span", null, Object.values(QUADS).map((q) => `${q.glyph} ${q.label} ${int(groups.filter((x) => x.quad.key === q.key).length)}`).join("   ·   ")));
    s2.append(h2, rpTable(["Regional head", "Outlets", "Monthly target", "Target (TD)", "Actual (TD)", "Ach. (TD)", lm, "Projected", "Proj. ach.", "MoM change", "MoM", { label: "Momentum", c: true }],
      groups.map((x) => [x.name, int(x.outlets), bdt(x.monthlyTarget), bdt(x.target), bdt(x.actual), { text: npct(x.achievement), cls: achCls(x.achievement) }, bdt(x.lastMonth || null), bdt(x.projected),
        { text: npct(x.projectedAchievement), cls: achCls(x.projectedAchievement) }, { text: bdt(x.delta), cls: (x.delta || 0) >= 0 ? "pos" : "neg" }, { text: spct(x.mom), cls: (x.mom || 0) >= 0 ? "pos" : "neg" },
        { html: `<span class="rp-pill ${x.quad.key === "accelerating" ? "good" : x.quad.key === "atrisk" ? "bad" : "watch"}">${x.quad.glyph} ${x.quad.label}</span>`, cls: "c" }])));
    p1.append(s2);
    // Fill the rest of the cover with network-level outlet movers so page 1 stands alone as a summary.
    const mv = list.filter((r) => r.lastMonthSales && nnum(r.projectedVsLastMonth) !== null).sort((x, y) => y.projectedVsLastMonth - x.projectedVsLastMonth);
    const buildMovers = (count) => {
      const gain = mv.slice(0, count).filter((r) => r.projectedVsLastMonth > 0), loss = mv.slice(-count).reverse().filter((r) => r.projectedVsLastMonth < 0);
      const sec = el("section", "rp-section"), h = el("h3", "rp-h", "Network movers"), cols = el("div", "rp-cols");
      h.append(el("span", null, `largest outlet-level swings against ${lm}`));
      const rows = (l) => l.map((r) => [{ text: oname(r), title: oname(r) }, { text: disp(r.leader || r.regionalHead), cls: "muted" }, bdt(r.lastMonthSales), { text: bdt(r.projectedVsLastMonth), cls: r.projectedVsLastMonth >= 0 ? "pos" : "neg" }, { text: spct(r.momGrowth), cls: (r.momGrowth || 0) >= 0 ? "pos" : "neg" }]);
      const hd = ["Outlet", "RHO", lm, "Change", "MoM"], gw = el("div"), lw = el("div");
      gw.append(el("h3", "rp-h", `▲ Top ${int(gain.length)} gainers`), gain.length ? rpTable(hd, rows(gain)) : el("div", "rp-empty", "No outlet is projected above its last-month sales."));
      lw.append(el("h3", "rp-h", `▼ Steepest ${int(loss.length)} declines`), loss.length ? rpTable(hd, rows(loss)) : el("div", "rp-empty", "No outlet is projected below its last-month sales."));
      cols.append(gw, lw); sec.append(h, cols);
      return sec;
    };
    const moversSec = mv.length ? buildMovers(6) : null;
    if (moversSec) p1.append(moversSec);
    p1.append(foot()); sheet.append(p1);
    // A4 landscape at 96 dpi: if the movers push the cover past one page, move them to a page of their own.
    const PAGE_H = 794, CLEAR = 30, contentH = (n) => { const prev = n.style.minHeight; n.style.minHeight = "0"; const h = n.offsetHeight; n.style.minHeight = prev; return h; };
    if (moversSec && contentH(p1) + CLEAR > PAGE_H) {
      moversSec.remove();
      const spill = el("section", "report-page");
      spill.append(topline(`${fmonth(rm)} · Network movers`), buildMovers(14), foot());
      sheet.append(spill);
    }
    groups.forEach((gr, i) => {
      const page = el("section", "report-page"), head = el("div", "rp-head"), who = el("div", "rp-who"), whoText = el("div");
      page.append(topline(`${fmonth(rm)} · Regional head ${i + 1} of ${groups.length}`));
      const divs = [...new Set(gr.rows.map((r) => disp(r.division)).filter((v) => v !== "—"))], zon = [...new Set(gr.rows.map((r) => disp(r.zonal)).filter((v) => v !== "—"))];
      whoText.append(el("h1", null, gr.name), el("p", null, `${int(gr.outlets)} outlets · ${int(zon.length)} zonal${zon.length === 1 ? "" : "s"} · ` + (divs.slice(0, 4).join(", ") || "no division recorded") + (divs.length > 4 ? ` +${divs.length - 4} more` : "")));
      who.append(el("div", "rp-rank", String(i + 1)), whoText);
      head.append(who, el("span", "rp-chip " + (gr.quad.key === "accelerating" ? "good" : gr.quad.key === "atrisk" ? "bad" : gr.quad.key === "holding" ? "info" : "watch"), `${gr.quad.glyph} ${gr.quad.label}`));
      page.append(head);
      const ts = el("section", "rp-section"), g1 = el("div", "rp-tiles"), g2 = el("div", "rp-tiles");
      g1.append(rpTile("Monthly target", bdt(gr.monthlyTarget)), rpTile("Target till date", bdt(gr.target)), rpTile("Actual till date", bdt(gr.actual), bdt(gr.actual - gr.target) + " gap", gr.actual >= gr.target ? "pos" : "neg"),
        rpTile("Achievement till date", npct(gr.achievement), perfTone(gr.achievement).label, tileTone(gr.achievement)));
      g2.style.marginTop = "6px";
      g2.append(rpTile(lm + " sales", bdt(gr.lastMonth || null), `${int(gr.hasBase)} of ${int(gr.outlets)} with a base`), rpTile("Projected month-end", bdt(gr.projected), bdt(gr.projected - gr.monthlyTarget) + " vs target", gr.projected >= gr.monthlyTarget ? "pos" : "neg"),
        rpTile("MoM change", bdt(gr.delta), "versus " + lm, (gr.delta || 0) >= 0 ? "pos" : "neg"), rpTile("MoM growth", spct(gr.mom), growthTone(gr.mom).label, (gr.mom || 0) >= 0 ? "pos" : "neg"));
      ts.append(g1, g2); page.append(ts);
      const ms = el("section", "rp-section"), meters = el("div", "rp-meters"), mt = (v) => ({ good: "pos", bad: "neg" }[perfTone(v).key] || "neu");
      meters.append(rpMeter("Actual vs target, till date", `${bdt(gr.actual)} / ${bdt(gr.target)} · ${npct(gr.achievement)}`, gr.achievement, mt(gr.achievement)),
        rpMeter("Projected vs monthly target", `${bdt(gr.projected)} / ${bdt(gr.monthlyTarget)} · ${npct(gr.projectedAchievement)}`, gr.projectedAchievement, mt(gr.projectedAchievement)));
      ms.append(el("h3", "rp-h", "Progress"), meters); page.append(ms);
      const cols = el("div", "rp-cols"), left = el("div"), right = el("div");
      const top = gr.rows.slice().sort((x, y) => (nnum(y.projectedSales) || 0) - (nnum(x.projectedSales) || 0)).slice(0, 10);
      const lh = el("h3", "rp-h", "Largest outlets by projected sales"); lh.append(el("span", null, `top ${int(top.length)} of ${int(gr.outlets)}`));
      left.append(lh, rpTable(["Outlet", lm, "Projected", "MoM", "Proj. ach."], top.map((r) => [{ text: oname(r), title: oname(r) }, bdt(r.lastMonthSales), bdt(r.projectedSales), { text: spct(r.momGrowth), cls: (r.momGrowth || 0) >= 0 ? "pos" : "neg" }, { text: npct(r.projectedAchievement), cls: achCls(r.projectedAchievement) }])));
      const allRisk = gr.rows.filter((r) => nnum(r.momGrowth) !== null && r.momGrowth < -0.02 && nnum(r.projectedAchievement) !== null && r.projectedAchievement < 1).sort((x, y) => (nnum(x.projectedGap) || 0) - (nnum(y.projectedGap) || 0));
      const risk = allRisk.slice(0, 10), rh = el("h3", "rp-h", "Needs attention");
      rh.append(el("span", null, "declining and below monthly target")); right.append(rh);
      if (risk.length) {
        right.append(rpTable(["Outlet", lm, "Projected", "MoM", "Target gap"], risk.map((r) => [{ text: oname(r), title: oname(r) }, bdt(r.lastMonthSales), bdt(r.projectedSales), { text: spct(r.momGrowth), cls: "neg" }, { text: bdt(r.projectedGap), cls: "neg" }])));
        if (allRisk.length > risk.length) { const more = el("p", null, `Showing the 10 largest gaps of ${int(allRisk.length)} outlets in this state.`); more.style.cssText = "margin:5px 0 0;font-size:7.5px;color:#6b8395"; right.append(more); }
      } else right.append(el("div", "rp-empty", "No outlet in this portfolio is both declining month-on-month and behind its monthly target."));
      cols.append(left, right); page.append(cols, foot()); sheet.append(page);
    });
    const pages = [...sheet.querySelectorAll(".report-page")];
    pages.forEach((pg, i) => { const s = pg.querySelector(".rp-pageno"); if (s) s.textContent = `Page ${i + 1} of ${pages.length}`; });
    $("#reportMeta").textContent = `${fmonth(rm)} · ${int(groups.length)} regional heads · ${int(list.length)} outlets · ${pages.length} pages · Filters: ${filterText}`;
  }
  function openReport() {
    // Open first: the layout has to be live for the page-fit measurement to work.
    $("#reportOverlay").classList.add("is-open");
    document.body.style.overflow = "hidden";
    buildReport(inView());
    $("#reportOverlay").scrollTop = 0;
    $("#reportClose").focus();
  }
  function closeReport() {
    if (!$("#reportOverlay").classList.contains("is-open")) return false;
    $("#reportOverlay").classList.remove("is-open");
    document.body.style.overflow = "";
    return true;
  }
  let h2cPromise = null;
  const loadH2C = () => (h2cPromise = h2cPromise || new Promise((ok, fail) => { const s = document.createElement("script"); s.src = "assets/vendor/html2canvas.min.js"; s.onload = ok; s.onerror = () => { h2cPromise = null; fail(new Error("load")); }; document.head.append(s); }));
  async function reportPng() {
    const busy = $("#reportBusy"), btn = $("#reportPng");
    busy.hidden = false; btn.disabled = true;
    try {
      await loadH2C();
      const pages = [...document.querySelectorAll("#reportSheet .report-page")], pageH = pages[0].offsetHeight, pageW = pages[0].offsetWidth;
      // Browsers cap canvases near 16384px a side, so scale to fit and split into parts if even 1x overflows.
      const MAX = 16000, scale = Math.max(1, Math.min(2, MAX / (pageH * pages.length))), perPart = Math.max(1, Math.floor(MAX / (pageH * scale))), shots = [];
      for (const p of pages) shots.push(await window.html2canvas(p, { scale, backgroundColor: "#ffffff", logging: false, useCORS: true, windowWidth: pageW }));
      const parts = [];
      for (let i = 0; i < shots.length; i += perPart) parts.push(shots.slice(i, i + perPart));
      for (let pi = 0; pi < parts.length; pi++) {
        const grp = parts[pi], c = document.createElement("canvas");
        c.width = grp[0].width; c.height = grp.reduce((s, x) => s + x.height, 0);
        const ctx = c.getContext("2d");
        ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, c.width, c.height);
        let y = 0;
        grp.forEach((x) => { ctx.drawImage(x, 0, y); y += x.height; });
        const blob = await new Promise((res) => c.toBlob(res, "image/png")), url = URL.createObjectURL(blob), a = document.createElement("a");
        a.href = url; a.download = `rho-summary-report_${S.netTo}${parts.length > 1 ? "-part" + (pi + 1) : ""}.png`;
        document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      }
    } catch (e) {
      console.error(e);
      $("#reportMeta").textContent = 'Could not render the image. Use "Print or save as PDF" instead.';
    } finally { busy.hidden = true; btn.disabled = false; }
  }

  function netFilesPanel() {
    const head = `<div class="panel-head"><div><h2>Outlet network files</h2><p>Feed the Outlet network and Growth & momentum pages. Recognised by their layout, so filenames can change.</p></div>`;
    if (!S.net) {
      loadNet();
      return `<section class="panel">${head}</div><div class="panel-body"><p class="muted" style="margin:0">${S.netErr ? `network.json could not be loaded (${esc(S.netErr)}).` : "Loading…"}</p></div></section>`;
    }
    const src = S.net.source || {}, files = src.drive?.files || {}, used = src.sourceFiles || {};
    const roles = [["outletMaster", "Outlet master"], ["dayWiseTarget", "Day-wise target"], ["dayWiseSales", "Day-wise sales"], ["lastMonth", "Last month (SPLY)"]];
    return `<section class="panel">${head}${src.drive?.folderUrl ? `<div class="panel-tools"><a class="btn" href="${esc(src.drive.folderUrl)}" target="_blank" rel="noopener">Open Drive folder</a></div>` : ""}</div>
      <div class="table-wrap"><table><thead><tr><th>File</th><th>Type</th><th>Data</th></tr></thead><tbody>
      ${roles.map(([k, t]) => `<tr><td class="cell-primary">${esc(files[k] || used[k] || "—")}</td><td>${esc(t)}</td><td>${k === "dayWiseSales" ? `Sales through ${fdate(src.salesThroughDate)}` : k === "dayWiseTarget" ? fmonth(src.reportMonth || S.net.month) : k === "lastMonth" ? (src.lastMonth?.monthLabel ? `${esc(src.lastMonth.monthLabel)}, ${int(src.lastMonth.matchedOutlets)} outlets matched` : "Not in the folder, so last-month figures show as —") : `${int(S.net.rows.length)} outlets`}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="panel-body"><p class="muted" style="margin:0;max-width:78ch">All four come from the mother Drive folder (any sub-folder, any name): day-wise sales is the till-date sales file (Outlet, Date, Article Division, POS NSI), last month is the Business Performance Report whose SPLY period is the previous month. The same hourly refresh picks them up${driveNote() ? `; last synced ${esc(driveNote())}` : ""}. If a required workbook is missing or broken, the pages keep the last good data.</p></div></section>`;
  }

  function wireNet(root) {
    $$("[data-ndrill]", root).forEach((n) => {
      const go = (e) => { e.stopPropagation(); NDRILL.get(n.dataset.ndrill)?.(); };
      n.onclick = go;
      if (n.tagName === "TR") n.onkeydown = (e) => { if (e.key === "Enter") go(e); };
    });
    $$("[data-ndrill-clear]", root).forEach((b) => (b.onclick = () => { S.on.drill = null; render(); }));
    $$("[data-noutlet]", root).forEach((n) => { n.onclick = () => openNetOutlet(n.dataset.noutlet); n.onkeydown = (e) => { if (e.key === "Enter") openNetOutlet(n.dataset.noutlet); }; });
    $$("[data-nset]", root).forEach((b) => (b.onclick = () => {
      const [a, k] = b.dataset.nset.split(".");
      if (a === "netm") S.netMode = b.dataset.val; else S[a][k] = b.dataset.val;
      render();
    }));
    $$("[data-nsel]", root).forEach((s) => (s.onchange = () => { const [a, k] = s.dataset.nsel.split("."); S[a][k] = s.value; render(); }));
    $$("[data-ndate]", root).forEach((inp) => (inp.onchange = () => {
      if (!inp.value) return;
      S[inp.dataset.ndate] = inp.value;
      if (S.netFrom > S.netTo) S.netFrom = S.netTo.slice(0, 8) + "01";
      changed();
    }));
    $$("[data-ncsv]", root).forEach((b) => (b.onclick = () => { const f = NCSV[b.dataset.ncsv]; if (f) saveCsv(...f()); }));
    $$("[data-nreport]", root).forEach((b) => (b.onclick = openReport));
  }

  // ------------------------------------------------------------------ consumable & wastage
  // data/cw.json is built by scripts/cw/refresh.py from the Consumable & Wastage Control Drive folder
  // (Target.txt, Sales-Till, Zone Distribution, CONSUMABLE and WASTAGE SAP exports). Loaded on first visit.
  // Aggregate rule everywhere: sum(numerator) / sum(denominator); outlet percentages are never averaged
  // for a business result, except the benchmark "outlet average", which is labelled as such.
  const CWM = {
    // Consumable issues post to SAP in batches, so the denominator is each outlet's sales up to its own
    // last consumable posting day inside the selected range (consumableSales), not plain sales.
    consumableRate: { label: "Consumable % on sales", short: "Consumable %", num: "consumable", den: "consumableSales", target: "consumableTarget", valueLabel: "Consumable value" },
    wastageSalesRate: { label: "Wastage % on sales", short: "Wastage on sales %", num: "wastage", den: "sales", target: "wastageSalesTarget", valueLabel: "Wastage value" },
    wastagePnpRate: { label: "Wastage % on PNP sales", short: "Wastage on PNP %", num: "wastage", den: "pnpSales", target: "wastagePnpTarget", valueLabel: "Wastage value" },
  };
  const CWK = Object.keys(CWM);
  const CW_TOL = 0.0001; // 0.01 percentage point
  const CW_METRIC_OPTS = CWK.map((k) => [k, CWM[k].short]);
  const CW_STATUS = [["all", "All outlets"], ["above", "Above any target"], ["within", "Within all targets"], ["unmapped", "Unmapped outlets"], ["reversal", "Net reversal outlets"]];
  function cwStatus(actual, target, numerator = 0) {
    if (!isNum(actual) || !isNum(target)) return { key: "neutral", cls: "idle", label: "No target" };
    if (numerator < 0) return { key: "info", cls: "info", label: "Net reversal" };
    if (Math.abs(actual - target) <= CW_TOL) return { key: "near", cls: "warn", label: "At target" };
    return actual < target ? { key: "good", cls: "good", label: "Within target" } : { key: "bad", cls: "bad", label: "Above target" };
  }
  function cwAvgVs(avg, target) {
    if (!isNum(avg) || !isNum(target)) return { cls: "idle", label: "Not comparable" };
    if (Math.abs(avg - target) <= CW_TOL) return { cls: "warn", label: "Average at target" };
    return avg < target ? { cls: "good", label: "Target > Outlet avg" } : { cls: "bad", label: "Outlet avg > Target" };
  }
  const shiftDay = (iso, n) => { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const dayCount = (a, b) => Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000) + 1;
  const pts = (v, d = 2) => (isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + " pp" : "—");
  const cwPct = (v) => pct(v, 2);
  const csv4 = (v) => (isNum(v) ? (v * 100).toFixed(4) : "");

  function loadCw() {
    if (S.cw || S.cwLoading) return;
    S.cwLoading = true; S.cwErr = null;
    fetch("data/cw.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => { prepCw(d); S.cw = d; })
      .catch((e) => { S.cwErr = e.message; })
      .finally(() => { S.cwLoading = false; if (CW_PAGES.has(S.page) || S.page === "dq") render(); });
  }
  function prepCw(d) {
    const v = (x) => (x == null || String(x).trim() === "" ? NET_MISS : String(x).trim());
    d.outlets.forEach((o) => {
      const own = /^own/i.test(o.ownership || "") ? "Own" : /^fr/i.test(o.ownership || "") ? "Franchise" : o.ownership;
      o.c = o.code; o.nm = o.name;
      o.dim = { rl: v(o.regionalLeader), zn: v(o.zone), div: v(o.division), dis: v(o.district), fmt: v(o.format), own: v(own), pnp: v(o.pnpStatus), loc: v(o.locationType), area: v(o.area), crit: v(o.criteria) };
    });
    d.byCode = new Map(d.outlets.map((o) => [o.code, o]));
    S.cwv.from = d.dateRange.min; S.cwv.to = d.dateRange.max;
  }
  function cwGuard() {
    if (S.cw) return "";
    loadCw();
    return S.cwErr
      ? `<p class="empty">The consumable and wastage data could not be loaded (${esc(S.cwErr)}). Run the "Refresh data" workflow on GitHub, then reload this page.</p>`
      : '<p class="empty">Loading consumable and wastage data…</p>';
  }

  // ---- aggregation (unchanged rules from the consumable & wastage dashboard)
  const cwEmpty = () => ({ sales: 0, pnpSales: 0, consumable: 0, wastage: 0, consumableSales: 0 });
  function cwAdd(b, r) { b.sales += r.sales || 0; b.pnpSales += r.pnpSales || 0; b.consumable += r.consumable || 0; b.wastage += r.wastage || 0; b.consumableSales += r.consumableSales || 0; }
  // Last day each outlet posted consumable value inside the range. A day whose issues and reversals
  // cancel to zero booked nothing, so it does not extend the window.
  let cwCutCache = { key: null, map: null };
  function cwCutoffs(from, to) {
    const key = from + "|" + to;
    if (cwCutCache.key === key) return cwCutCache.map;
    const map = new Map();
    for (const r of S.cw.daily) {
      if (!r.consumable || r.date < from || r.date > to) continue;
      const cur = map.get(r.code);
      if (cur === undefined || r.date > cur) map.set(r.code, r.date);
    }
    return (cwCutCache = { key, map }).map;
  }
  // Stamp each daily row with the sales that count towards its outlet's consumable rate, so every
  // aggregation path inherits the rule. One window is live at a time.
  function cwStamp(from, to) {
    const cut = cwCutoffs(from, to);
    for (const r of S.cw.daily) { const c = cut.get(r.code); r.consumableSales = r.date >= from && r.date <= to && c && r.date <= c ? r.sales || 0 : 0; }
  }
  function cwDecorate(o, b) {
    const m = { ...o, ...(b || cwEmpty()) };
    m.statuses = {}; m.excess = {};
    CWK.forEach((k) => {
      const def = CWM[k];
      m[k] = ratio(m[def.num], m[def.den]);
      m.statuses[k] = cwStatus(m[k], m[def.target], m[def.num]);
      const t = m[def.target], base = m[def.den];
      // Taka over target: this is what ranks the exception list financially.
      m.excess[k] = isNum(m[k]) && isNum(t) && base > 0 && m[k] > t ? (m[k] - t) * base : 0;
    });
    m.aboveAny = CWK.some((k) => m.statuses[k].key === "bad");
    m.hasTarget = CWK.some((k) => m.statuses[k].key !== "neutral");
    m.withinAll = m.hasTarget && !m.aboveAny;
    // Wastage on sales and on PNP describe the same taka twice, so only the larger counts.
    m.excessConsumable = m.excess.consumableRate;
    m.excessWastage = Math.max(m.excess.wastageSalesRate, m.excess.wastagePnpRate);
    m.excessTotal = m.excessConsumable + m.excessWastage;
    return m;
  }
  function cwWeightedTarget(list, k) {
    const def = CWM[k]; let w = 0, d = 0;
    list.forEach((r) => { const base = r[def.den] || 0, t = r[def.target]; if (base > 0 && isNum(t)) { w += base * t; d += base; } });
    return d > 0 ? w / d : null;
  }
  function cwSummarize(list) {
    const s = { ...cwEmpty(), aboveAny: 0, mapped: 0, excessConsumable: 0, excessWastage: 0, excessTotal: 0, outlets: list.length, targets: {}, averages: {}, statuses: {} };
    list.forEach((r) => { cwAdd(s, r); s.aboveAny += +r.aboveAny; s.mapped += +r.mapped; s.excessConsumable += r.excessConsumable || 0; s.excessWastage += r.excessWastage || 0; s.excessTotal += r.excessTotal || 0; });
    CWK.forEach((k) => {
      const def = CWM[k], vals = list.map((r) => r[k]).filter(isNum);
      s[k] = ratio(s[def.num], s[def.den]);
      s.targets[k] = cwWeightedTarget(list, k);
      s.averages[k] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      s.statuses[k] = cwStatus(s[k], s.targets[k], s[def.num]);
    });
    return s;
  }
  function cwBuckets(codes, from, to) {
    const b = new Map(); codes.forEach((c) => b.set(c, cwEmpty()));
    for (const r of S.cw.daily) { if (r.date < from || r.date > to) continue; const x = b.get(r.code); if (x) cwAdd(x, r); }
    const cut = cwCutoffs(from, to);
    b.forEach((x, c) => (x.consumableCutoff = cut.get(c) || null));
    return b;
  }
  function cwDaily(codes, from, to) {
    const m = new Map();
    for (const r of S.cw.daily) {
      if (!codes.has(r.code) || r.date < from || r.date > to) continue;
      if (!m.has(r.date)) m.set(r.date, { date: r.date, ...cwEmpty() });
      cwAdd(m.get(r.date), r);
    }
    const out = [...m.values()].sort((a, b) => a.date.localeCompare(b.date));
    out.forEach((x) => CWK.forEach((k) => (x[k] = ratio(x[CWM[k].num], x[CWM[k].den]))));
    return out;
  }
  const CW_TESTS = { above: (r) => r.aboveAny, within: (r) => r.withinAll, unmapped: (r) => !r.mapped, reversal: (r) => r.consumable < 0 || r.wastage < 0 };
  function cwView() {
    const d = S.cw, f = S.cwv, from = f.from, to = f.to, bad = from > to;
    const cand = inView();
    if (!bad) cwStamp(from, to);
    const buckets = bad ? new Map() : cwBuckets(cand.map((o) => o.code), from, to);
    let metrics = cand.map((o) => cwDecorate(o, buckets.get(o.code)));
    if (f.status !== "all") metrics = metrics.filter(CW_TESTS[f.status]);
    const codes = new Set(metrics.map((r) => r.code));
    const v = { from, to, bad, metrics, codes, daily: bad ? [] : cwDaily(codes, from, to), summary: cwSummarize(metrics), prior: null };
    // Compare with the equal-length window just before the selection, only when it fits in the data.
    const len = bad ? 0 : dayCount(from, to), pTo = shiftDay(from, -1), pFrom = shiftDay(pTo, -(len - 1));
    v.priorPeriod = !bad && pFrom >= d.dateRange.min ? { from: pFrom, to: pTo } : null;
    if (f.compare && v.priorPeriod) {
      cwStamp(pFrom, pTo);
      const pb = cwBuckets([...codes], pFrom, pTo);
      const pm = metrics.map((r) => cwDecorate(d.byCode.get(r.code), pb.get(r.code)));
      const byC = new Map(pm.map((r) => [r.code, r]));
      metrics.forEach((r) => (r.prior = byC.get(r.code) || null));
      v.prior = { from: pFrom, to: pTo, summary: cwSummarize(pm), daily: cwDaily(codes, pFrom, pTo) };
      cwStamp(from, to); // restore the selected window for anything reading raw rows later
    }
    return v;
  }
  function cwGroups(metrics, dim) {
    const g = new Map();
    metrics.forEach((r) => { const k = dim === "outlet" ? r.code : r[dim] || "Unmapped"; if (!g.has(k)) g.set(k, []); g.get(k).push(r); });
    return [...g].map(([key, rows]) => ({ key, name: dim === "outlet" ? rows[0].name : key, code: dim === "outlet" ? key : null, sub: dim === "outlet" ? `${key}, ${rows[0].zone}` : `${int(rows.length)} outlets`, rows, ...cwSummarize(rows) }));
  }

  // ---- shared page parts
  const cwSel = (key, opts, label) => `<select class="sel" data-cwsel="${key}" aria-label="${esc(label)}">${opts.map(([v, t]) => `<option value="${v}" ${S.cwv[key] === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  function cwBar(v) {
    const d = S.cw, f = S.cwv;
    const quick = [["", "Quick period"], ["all", "Full loaded period"], ["7", "Last 7 days"], ["14", "Last 14 days"], ["mtd", "Month to date"]];
    if (!UI.cwBarOpen) {
      const status = CW_STATUS.find((x) => x[0] === f.status)[1];
      return `<section class="panel ui-slim"><div class="panel-head"><div><h2>Period and scope</h2><p>${v.bad ? "The From date is after the To date." : `${fdate(f.from)} to ${fdate(f.to)} · ${dayCount(f.from, f.to)} days · ${esc(status)}${f.compare && v.prior ? " · compared with the prior period" : ""}`}</p></div>
        <div class="panel-tools"><button class="btn" data-uitoggle="cwBarOpen" aria-expanded="false">Show</button></div></div></section>`;
    }
    return `<section class="panel"><div class="panel-head"><div><h2>Period and scope</h2><p>${v.bad ? "The From date is after the To date." : `${fdate(f.from)} to ${fdate(f.to)}, ${dayCount(f.from, f.to)} days. Data loaded ${fdate(d.dateRange.min)} to ${fdate(d.dateRange.max)}.`}</p></div>
      <div class="panel-tools">
        <label class="net-date">From<input type="date" data-cwdate="from" value="${f.from}" min="${d.dateRange.min}" max="${d.dateRange.max}"></label>
        <label class="net-date">To<input type="date" data-cwdate="to" value="${f.to}" min="${d.dateRange.min}" max="${d.dateRange.max}"></label>
        <select class="sel" data-cwquick aria-label="Quick period">${quick.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select>
        ${cwSel("status", CW_STATUS, "Performance status")}
        <button class="btn" data-cwcompare aria-pressed="${!!(f.compare && v.prior)}" ${v.priorPeriod ? "" : "disabled"} title="${v.priorPeriod ? `Compare with ${fdate(v.priorPeriod.from)} to ${fdate(v.priorPeriod.to)}` : "No equal-length period before this one in the loaded data"}">Compare with prior period</button>
        <button class="btn" data-uitoggle="cwBarOpen" aria-expanded="true">Hide</button>
      </div></div>
      <div class="panel-body cw-raw"><span class="muted">Raw rows for the outlets and dates in view:</span>
        <button class="btn" data-cwraw="daily">Outlet-day rows (CSV)</button>
        <button class="btn" data-cwraw="materials">Material postings (CSV)</button></div></section>`;
  }
  const cwDelta = (cur, pri) => {
    if (!isNum(cur) || !isNum(pri)) return "";
    const ch = cur - pri;
    if (Math.abs(ch) <= CW_TOL / 10) return '<span class="flat">■ no change</span>';
    return `<span class="${ch > 0 ? "down" : "up"}">${ch > 0 ? "▲" : "▼"} ${pts(ch)}</span>`; // lower is better
  };
  const cwValDelta = (cur, pri) => (isNum(cur) && isNum(pri) && pri ? `<span class="flat">${cur >= pri ? "▲" : "▼"} ${Math.abs(((cur - pri) / Math.abs(pri)) * 100).toFixed(1)}%</span>` : "");
  function cwKpis(v) {
    const s = v.summary, p = v.prior?.summary;
    const rateCard = (k, accent, foot) => kpi({ label: CWM[k].label, value: cwPct(s[k]), accent,
      sub: `${chip(s.statuses[k])}<span>Target ${cwPct(s.targets[k])}</span>`,
      foot: `<span>${foot}</span><span>${p ? cwDelta(s[k], p[k]) : chip({ ...cwAvgVs(s.averages[k], s.targets[k]), label: "Avg " + cwPct(s.averages[k]) })}</span>` });
    const shares = s.excessTotal > 0 ? [s.excessConsumable, s.excessWastage].map((x) => Math.max(0, Math.min(100, (x / s.excessTotal) * 100))) : [0, 0];
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr))">
      ${kpi({ label: "Overall POS NSI", value: bdt(s.sales), sub: `PNP sales <strong>${bdt(s.pnpSales)}</strong>`, foot: `<span>${int(s.outlets)} outlets</span><span>${p ? cwValDelta(s.sales, p.sales) : ""}</span>`, accent: "var(--series-2)" })}
      ${rateCard("consumableRate", "var(--series-1)", `Value ${bdt(s.consumable)} on ${bdt(s.consumableSales)} base`)}
      ${rateCard("wastageSalesRate", "var(--series-3)", `Value ${bdt(s.wastage)}`)}
      ${rateCard("wastagePnpRate", "var(--series-2)", "FRESH PRODUCE base")}
      <div class="kpi" style="--accent:var(--bad)"><span class="label">Amount above target</span><span class="value down" title="${esc(exact(s.excessTotal))}">${bdt(s.excessTotal)}</span>
        <span class="sub"><span><i class="cw-key c"></i>Consumable ${bdt(s.excessConsumable)}</span><span><i class="cw-key w"></i>Wastage ${bdt(s.excessWastage)}</span></span>
        <div class="cw-split" role="img" aria-label="Consumable ${shares[0].toFixed(1)}%, wastage ${shares[1].toFixed(1)}% of the amount above target">${shares[0] ? `<span class="c" style="flex-grow:${shares[0]}"></span>` : ""}${shares[1] ? `<span class="w" style="flex-grow:${shares[1]}"></span>` : ""}</div>
        <span class="foot"><span>${int(s.aboveAny)} outlets above at least one target</span><span>${p ? cwValDelta(s.excessTotal, p.excessTotal) : `${int(s.outlets - s.mapped)} unmapped`}</span></span></div>
    </div>`;
  }
  const cwOutletAttr = (x) => `data-cwoutlet="${esc(x.code)}" tabindex="0"`;
  // Group table used by the overview comparison and the league tables. Clicking a group lists its outlets.
  function cwGroupTable(id, v, dim, metric, extraTools, title, D) {
    const def = CWM[metric], gd = D ? null : gdrill(id, dim);
    const CWD = { rl: "regionalLeader", zn: "zone", outlet: "outlet" };
    const rows = D ? cwGroups(v.metrics.filter(D.inPath), CWD[D.at]) : gd ? cwGroups(v.metrics.filter((r) => (r[dim] || "Unmapped") === gd.key), "outlet") : cwGroups(v.metrics, dim);
    if (D && D.at === "zn") rows.forEach((x) => (x.sub = D.zsub(x.key, x.sub)));
    const lvl = D ? CWD[D.at] : gd ? "outlet" : dim;
    if (D) title = D.V.zn ? `Outlets of ${D.V.zn}` : D.V.rl ? `Zonals of ${D.V.rl}` : { rl: "Regional leaders", zn: "Zonal leaders", outlet: "Outlets" }[D.at];
    rows.forEach((x) => { x.metric = x[metric]; x.target = x.targets[metric]; x.variance = isNum(x.metric) && isNum(x.target) ? x.metric - x.target : null; x.base = x[def.den]; x.value = x[def.num]; });
    return mountTable(id, {
      title: gd ? `Outlets of ${gd.key}` : title, file: D ? D.file(`cw_${metric}`) : `cw_${id}_${lvl}_${metric}`, stamp: S.cwv.to, banner: D ? D.crumbs : gBanner(id, gd),
      desc: (n) => `${int(n)} ${D ? ({ regionalLeader: "regional leaders", zone: n === 1 ? "zonal" : "zonals", outlet: n === 1 ? "outlet" : "outlets" }[lvl]) : "rows"}. ${def.label}, weighted; lower is better. ${lvl === "outlet" ? "Click an outlet for its profile." : D && lvl === "regionalLeader" ? "Click a leader to see their zonals." : "Click a row to list its outlets."}`,
      rows, key: (x) => x.key, searchText: (x) => `${x.name} ${x.sub}`, defaultSort: "metric", tools: D ? `${D.tools}${extraTools}` : extraTools, pageSize: 25,
      rowAttr: (x) => (x.code ? cwOutletAttr(x) : D ? D.pick(x) : `data-gpick="${id}" data-glevel="${esc(dim)}" data-gkey="${esc(x.key)}" tabindex="0" title="List ${esc(x.name)}'s outlets"`),
      cols: [
        { k: "name", label: CW_LEVELS[lvl], fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => x.name, val: (x) => x.name },
        { k: "outlets", label: "Outlets", num: 1, fmt: (x) => int(x.outlets) },
        { k: "base", label: "Sales base", num: 1, fmt: (x) => bdt(x.base), csv: (x) => Math.round(x.base) },
        { k: "value", label: def.valueLabel, num: 1, fmt: (x) => bdt(x.value), csv: (x) => Math.round(x.value) },
        { k: "target", label: "Target", num: 1, fmt: (x) => cwPct(x.target), csv: (x) => csv4(x.target) },
        { k: "metric", label: "Weighted actual", num: 1, fmt: (x) => `<strong>${cwPct(x.metric)}</strong>`, csv: (x) => csv4(x.metric) },
        { k: "variance", label: "Variance", num: 1, fmt: (x) => `<span class="${x.variance > 0 ? "down" : "up"}">${pts(x.variance)}</span>`, csv: (x) => csv4(x.variance) },
        { k: "excessTotal", label: "Amount above target", num: 1, fmt: (x) => bdt(x.excessTotal), csv: (x) => Math.round(x.excessTotal) },
        { k: "st", label: "Status", val: (x) => cwStatus(x.metric, x.target, x.value).label, fmt: (x) => chip(cwStatus(x.metric, x.target, x.value)), csv: (x) => cwStatus(x.metric, x.target, x.value).label },
      ],
    });
  }

  // ---- overview
  function pageCW() {
    const g = cwGuard(); if (g) return g;
    const v = cwView(), f = S.cwv;
    const counts = { good: 0, near: 0, bad: 0, neutral: 0 };
    v.metrics.forEach((r) => { const k = r.statuses[f.statusMetric].key; counts[k === "info" ? "good" : k]++; });
    const tot = Math.max(1, counts.good + counts.near + counts.bad + counts.neutral), a = (counts.good / tot) * 100, b = a + (counts.near / tot) * 100, c = b + (counts.bad / tot) * 100;
    const donut = `<section class="panel cw-short"><div class="panel-head"><div><h2>Target position</h2><p>Outlets within, at and above target.</p></div><div class="panel-tools">${cwSel("statusMetric", CW_METRIC_OPTS, "Status metric")}</div></div>
      <div class="panel-body cw-donut"><div class="donut" style="background:conic-gradient(var(--good) 0 ${a}%, var(--warn) ${a}% ${b}%, var(--bad) ${b}% ${c}%, var(--surface-3) ${c}% 100%)"><div class="donut-center"><strong>${int(counts.good + counts.near + counts.bad)}</strong><span>comparable</span></div></div>
      <div class="cw-legend"><div><strong class="up">${int(counts.good)}</strong><span>Within</span></div><div><strong style="color:var(--warn)">${int(counts.near)}</strong><span>At target</span></div><div><strong class="down">${int(counts.bad)}</strong><span>Above</span></div><div><strong>${int(counts.neutral)}</strong><span>No target</span></div></div></div></section>`;
    const trend = `<section class="panel cw-short"><div class="panel-head"><div><h2>Rate trend</h2><p id="cwTrendSub"></p></div><div class="panel-tools">${cwSel("basis", [["daily", "Daily"], ["rolling7", "7-day rolling"], ["cumulative", "Period to date"]], "Basis")}</div></div>
      <div class="panel-body"><div class="chart-legend"><span><i class="swatch" style="background:var(--series-1)"></i>Consumable %</span><span><i class="swatch" style="background:var(--series-2)"></i>Wastage on PNP %</span><span><i class="swatch dash"></i>Targets</span>${v.prior ? '<span><i class="swatch dash"></i>Prior period (dashed, thin)</span>' : ""}</div>
      <div class="chart" id="cwTrend"></div><p class="note" id="cwTrendNote" hidden></p></div></section>`;
    let movers = "";
    if (v.prior) {
      const k = f.moversMetric, moved = v.metrics.filter((r) => r.prior && isNum(r[k]) && isNum(r.prior[k])).map((r) => ({ r, ch: r[k] - r.prior[k] })).filter((x) => Math.abs(x.ch) > CW_TOL);
      const list = (items, cls) => items.map(({ r, ch }) => `<div class="cw-row" ${cwOutletAttr(r)}><div><strong>${esc(r.code)} · ${esc(r.name)}</strong><small>${cwPct(r.prior[k])} → ${cwPct(r[k])}</small></div><span class="${cls}">${ch > 0 ? "▲" : "▼"} ${pts(Math.abs(ch)).replace("+", "")}</span></div>`).join("") || '<p class="net-empty">No material movement.</p>';
      movers = `<section class="panel"><div class="panel-head"><div><h2>Biggest movers</h2><p>${esc(CWM[k].label)} against ${fdate(v.prior.from)} to ${fdate(v.prior.to)}.</p></div><div class="panel-tools">${cwSel("moversMetric", CW_METRIC_OPTS, "Movers metric")}</div></div>
        <div class="panel-body grid-h"><div><h3 class="cw-h3">Worsened</h3>${list([...moved].sort((x, y) => y.ch - x.ch).slice(0, 6), "down")}</div><div><h3 class="cw-h3">Improved</h3>${list([...moved].sort((x, y) => x.ch - y.ch).slice(0, 6), "up")}</div></div></section>`;
    }
    const HD = leaderDrill("cwh", "cw-rank", v.metrics, "click an outlet for its profile", { rl: (r) => r.regionalLeader || "Unmapped", zn: (r) => r.zone || "Unmapped" });
    const rank = cwGroupTable("cw-rank", v, null, f.rankMetric, cwSel("rankMetric", CW_METRIC_OPTS, "Metric"), "Hierarchy comparison", HD);
    AFTER.push(() => cwTrend(v));
    const defs = S.cw.metricDefinitions || {};
    return `${cwBar(v)}${cwKpis(v)}<div class="grid-2">${trend}${donut}</div>${rank}${movers}
      <details class="panel cw-method"><summary>How these numbers are worked out</summary><div class="panel-body"><dl class="facts">
        ${[["PNP sales", defs.pnpSales], ["Consumable % on sales", defs.consumableRate], ["Consumable sales base", defs.consumableWindow], ["Wastage % on sales", defs.wastageSalesRate], ["Wastage % on PNP sales", defs.wastagePnpRate], ["SAP net value", defs.sapNetValue], ["Group results", defs.aggregateRate], ["Benchmark outlet average", defs.outletAverage],
          ["Amount above target", "For each metric an outlet is above target: (actual − target) × that metric's sales base. Consumable and wastage are added; the two wastage measures describe the same taka, so only the larger counts."],
          ["Period comparison", "The equal-length window just before the selected range, shown only when it falls inside the loaded data."]]
          .filter(([, t]) => t).map(([h, t]) => `<dt>${esc(h)}</dt><dd>${esc(t)}</dd>`).join("")}</dl></div></details>`;
  }
  // SAP consumable issues post in batches, so the daily consumable line swings on posting timing.
  // Smoothing is a ratio of sums over the window, never an average of daily percentages.
  function cwSmooth(rows, mode) {
    if (mode === "daily" || !rows.length) return rows;
    return rows.map((row, i) => {
      const t = cwEmpty();
      rows.slice(mode === "cumulative" ? 0 : Math.max(0, i - 6), i + 1).forEach((x) => cwAdd(t, x));
      const o = { date: row.date, ...t };
      CWK.forEach((k) => (o[k] = ratio(t[CWM[k].num], t[CWM[k].den])));
      return o;
    });
  }
  function cwTrend(v) {
    const host = $("#cwTrend");
    if (!host) return;
    if (!v.daily.length || !v.summary.sales) { host.innerHTML = '<p class="net-empty">No daily data for the selected scope.</p>'; return; }
    const mode = S.cwv.basis, W = Math.round(Math.max(300, Math.min(1200, host.clientWidth || 800))), narrow = W < 520;
    const H = Math.round(Math.max(152, Math.min(220, W * (narrow ? 0.45 : 0.2)))), m = { t: 10, r: narrow ? 12 : 20, b: 28, l: narrow ? 44 : 54 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const ser = [["consumableRate", "--series-1"], ["wastagePnpRate", "--series-2"]];
    const cur = cwSmooth(v.daily, mode), pri = v.prior ? cwSmooth(v.prior.daily, mode) : [];
    const vals = [...cur, ...pri].flatMap((x) => ser.map(([k]) => x[k])).concat(ser.map(([k]) => v.summary.targets[k])).filter(isNum);
    const max = Math.max(0.001, ...vals) * 1.18, n = Math.max(cur.length, pri.length);
    const X = (i) => m.l + (n === 1 ? pw / 2 : (i / (n - 1)) * pw), Y = (x) => m.t + ph - (Math.max(0, x || 0) / max) * ph;
    const path = (rows, k) => rows.map((x, i) => (isNum(x[k]) ? [X(i), Y(x[k])] : null)).filter(Boolean).map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const ticks = Math.max(2, Math.min(4, Math.floor(ph / 26)));
    let svg = "";
    for (let i = 0; i <= ticks; i++) { const val = (max / ticks) * i, y = Y(val); svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" style="stroke:var(--grid)"/><text x="${m.l - 8}" y="${y + 3.5}" text-anchor="end" class="cw-axis">${pct(val, 1)}</text>`; }
    const step = Math.max(1, Math.ceil(cur.length / (narrow ? 4 : 9)));
    cur.forEach((x, i) => { const last = i === cur.length - 1; if (i && !last && i % step) return; svg += `<text x="${i === 0 ? m.l : last ? W - m.r : X(i)}" y="${H - 10}" text-anchor="${i === 0 ? "start" : last ? "end" : "middle"}" class="cw-axis">${fdate(x.date, true)}</text>`; });
    ser.forEach(([k, c]) => { const t = v.summary.targets[k]; if (isNum(t)) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" style="stroke:var(${c})" stroke-dasharray="6 5" opacity=".7"><title>Target ${cwPct(t)}</title></line>`; });
    if (pri.length) ser.forEach(([k, c]) => { const d = path(pri, k); if (d) svg += `<path d="${d}" fill="none" style="stroke:var(${c})" stroke-width="1.4" stroke-dasharray="3 4" opacity=".7"/>`; });
    ser.forEach(([k, c]) => {
      const d = path(cur, k);
      if (d) svg += `<path d="${d}" fill="none" style="stroke:var(${c})" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
      cur.forEach((x, i) => { if (isNum(x[k])) svg += `<circle cx="${X(i).toFixed(1)}" cy="${Y(x[k]).toFixed(1)}" r="3.2" style="fill:var(${c})"><title>${fdate(x.date)} · ${CWM[k].short} ${cwPct(x[k])}</title></circle>`; });
    });
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Consumable and wastage rate trend">${svg}</svg>`;
    const label = mode === "rolling7" ? "7-day rolling" : mode === "cumulative" ? "period to date" : "daily";
    $("#cwTrendSub").textContent = v.prior ? `${label}. Solid ${fdate(v.from)} to ${fdate(v.to)}, dashed ${fdate(v.prior.from)} to ${fdate(v.prior.to)}.` : `Consumable on sales up to each outlet's last posting day; wastage on PNP sales. ${label}.`;
    // Flag a consumable line whose value lands on only a few days of the window.
    const cons = v.daily.map((x) => Math.max(0, x.consumable)), total = cons.reduce((s, x) => s + x, 0), quiet = cons.filter((x) => x < total * 0.02).length;
    const note = $("#cwTrendNote");
    if (mode === "daily" && total > 0 && v.daily.length >= 4 && quiet >= Math.max(2, Math.round(v.daily.length * 0.2))) {
      note.hidden = false;
      note.textContent = `Consumable issues post in batches: ${quiet} of ${v.daily.length} days in this range carry almost no consumable value, so the daily consumable line swings on posting timing. Switch the basis to 7-day rolling or period to date to read the trend. Wastage posts daily and is unaffected.`;
    }
  }

  // ---- league tables
  function pageCWL() {
    const g = cwGuard(); if (g) return g;
    const v = cwView(), f = S.cwv;
    return `${cwBar(v)}${cwGroupTable("cw-league", v, f.leagueDim, f.leagueMetric, `${cwSel("leagueDim", [["zone", "Zonal"], ["regionalLeader", "Regional leader"], ["division", "Division"], ["district", "District"], ["criteria", "Final criteria"]], "Level")}${cwSel("leagueMetric", CW_METRIC_OPTS, "Metric")}`, "League table")}`;
  }

  // ---- exceptions
  function cwExceptions(v) {
    const k = S.cwv.excMetric;
    return v.metrics.map((r) => {
      if (k === "all") { const worst = CWK.filter((m) => r.excess[m] > 0).sort((a, b) => r.excess[b] - r.excess[a])[0]; return { r, value: r.excessTotal, k: worst || null }; }
      return { r, value: r.excess[k], k };
    }).filter((x) => x.value > 0 && x.k).sort((a, b) => b.value - a.value);
  }
  function pageCWX() {
    const g = cwGuard(); if (g) return g;
    const v = cwView(), items = cwExceptions(v);
    const cons = v.metrics.reduce((s, r) => s + r.excess.consumableRate, 0), wast = v.metrics.reduce((s, r) => s + Math.max(r.excess.wastageSalesRate, r.excess.wastagePnpRate), 0);
    NCSV.cwx = () => ["cw_exception_worklist", ["Priority", "Outlet code", "Outlet name", "Regional leader", "Zonal", "District", "Final criteria", "Driver metric", "Actual %", "Target %", "Variance pp", "Amount above target", "Period from", "Period to"],
      items.map(({ r, value, k }, i) => [i + 1, r.code, r.name, r.regionalLeader, r.zone, r.district, r.criteria, CWM[k].label, csv4(r[k]), csv4(r[CWM[k].target]), isNum(r[k]) && isNum(r[CWM[k].target]) ? ((r[k] - r[CWM[k].target]) * 100).toFixed(4) : "", Math.round(value), v.from, v.to]), v.to];
    return `${cwBar(v)}<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr))">
      ${kpi({ label: "Amount above target", value: `<span class="down">${bdt(items.reduce((s, x) => s + x.value, 0))}</span>`, sub: `Across <strong>${int(items.length)}</strong> outlets in the selection`, accent: "var(--bad)" })}
      ${kpi({ label: "Consumable exposure", value: bdt(cons), sub: "Spend above the consumable target", foot: `<span>${int(v.metrics.filter((r) => r.excess.consumableRate > 0).length)} outlets</span>`, accent: "var(--series-1)" })}
      ${kpi({ label: "Wastage exposure", value: bdt(wast), sub: "Higher of the sales and PNP wastage gaps", foot: `<span>${int(v.metrics.filter((r) => Math.max(r.excess.wastageSalesRate, r.excess.wastagePnpRate) > 0).length)} outlets</span>`, accent: "var(--series-3)" })}</div>
      <section class="panel"><div class="panel-head"><div><h2>Ranked by value at stake</h2><p>Taka above target, largest first. Top 100 shown; the worklist CSV has every outlet. Click an outlet for its profile.</p></div>
        <div class="panel-tools">${cwSel("excMetric", [["all", "All metrics combined"], ...CW_METRIC_OPTS], "Metric")}${csvBtn("cwx")}</div></div>
      <div class="panel-body cw-list">${items.slice(0, 100).map(({ r, value, k }, i) => `<div class="cw-row" ${cwOutletAttr(r)}><span class="cw-rank">${i + 1}</span>
        <div><strong>${esc(r.code)} · ${esc(r.name)}</strong><small>${esc(r.zone)} · ${esc(r.regionalLeader)} · ${esc(CWM[k].short)} ${cwPct(r[k])} vs target ${cwPct(r[CWM[k].target])} (${pts(r[k] - r[CWM[k].target])})</small></div>
        <span class="cw-amt"><strong class="down">${bdt(value)}</strong><small>over target</small></span></div>`).join("") || '<p class="net-empty">No outlet in this selection is above its applicable target.</p>'}</div></section>`;
  }

  // ---- benchmarks
  function pageCWB() {
    const g = cwGuard(); if (g) return g;
    const v = cwView(), k = S.cwv.benchMetric, def = CWM[k];
    const rows = cwGroups(v.metrics, "criteria").map((x) => ({ ...x, target: x.targets[k], actual: x[k], avg: x.averages[k], base: x[def.den], gap: isNum(x.averages[k]) && isNum(x.targets[k]) ? x.averages[k] - x.targets[k] : null }));
    const table = mountTable("cw-bench", {
      title: "Target versus benchmark outlet average", file: `cw_benchmarks_${k}`, stamp: S.cwv.to,
      desc: (n) => `${int(n)} final criteria. Weighted actual is sum ÷ sum; outlet average is the simple average of outlet rates. Click a row to list its outlets in the register.`,
      rows, key: (x) => x.key, searchText: (x) => x.name, defaultSort: "name", defaultDir: "asc", tools: cwSel("benchMetric", CWK.map((x) => [x, CWM[x].label]), "Metric"),
      rowAttr: (x) => `data-cwcrit="${esc(x.key)}" tabindex="0" title="List ${esc(x.name)} outlets"`,
      cols: [
        { k: "name", label: "Final criteria", fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span>`, csv: (x) => x.name, val: (x) => x.name },
        { k: "outlets", label: "Outlets", num: 1, fmt: (x) => int(x.outlets) },
        { k: "base", label: "Sales base", num: 1, fmt: (x) => bdt(x.base), csv: (x) => Math.round(x.base) },
        { k: "target", label: "Target", num: 1, fmt: (x) => `<strong>${cwPct(x.target)}</strong>`, csv: (x) => csv4(x.target) },
        { k: "actual", label: "Weighted actual", num: 1, fmt: (x) => `<span class="rate-pair"><strong>${cwPct(x.actual)}</strong>${chip(cwStatus(x.actual, x.target, x[def.num]))}</span>`, csv: (x) => csv4(x.actual) },
        { k: "avg", label: "Outlet average", num: 1, fmt: (x) => `<strong>${cwPct(x.avg)}</strong>`, csv: (x) => csv4(x.avg) },
        { k: "gap", label: "Average vs target", num: 1, fmt: (x) => pts(x.gap), csv: (x) => csv4(x.gap) },
        { k: "hl", label: "Highlight", val: (x) => cwAvgVs(x.avg, x.target).label, fmt: (x) => chip(cwAvgVs(x.avg, x.target)), csv: (x) => cwAvgVs(x.avg, x.target).label },
      ],
    });
    const s = v.summary;
    return `${cwBar(v)}${table}<div class="grid-h">${CWK.map((x) => `<section class="panel"><div class="panel-body"><span class="muted" style="font-size:11.5px">Selected scope</span><h2 style="font-size:15px;margin:2px 0 10px">${esc(CWM[x].label)}</h2>
      <div class="stat-grid three"><div class="stat"><small>Weighted target</small><strong>${cwPct(s.targets[x])}</strong></div><div class="stat"><small>Weighted actual</small><strong>${cwPct(s[x])}</strong></div><div class="stat"><small>Outlet average</small><strong>${cwPct(s.averages[x])}</strong></div></div>
      <div style="margin-top:10px">${chip(cwAvgVs(s.averages[x], s.targets[x]))}</div></div></section>`).join("")}</div>`;
  }

  // ---- materials
  function cwMaterials(codes, from, to, limit) {
    const out = { consumable: [], wastage: [] };
    if (!codes.size || from > to) return out;
    Object.keys(out).forEach((kind) => {
      const t = new Map();
      for (const [date, code, id, value, qty] of S.cw.materialDaily[kind]) {
        if (!codes.has(code) || date < from || date > to) continue;
        const x = t.get(id) || [id, 0, 0]; x[1] += value; x[2] += qty; t.set(id, x);
      }
      // Reversals are netted before ranking; never sum per-outlet top lists.
      out[kind] = [...t.values()].filter((x) => x[1] > 0).sort((a, b) => b[1] - a[1] || a[0] - b[0]).slice(0, limit || Infinity);
    });
    return out;
  }
  function cwMatRows(rows, accent) {
    if (!rows.length) return '<p class="net-empty">No items with positive net value for the selected outlets and dates.</p>';
    const cat = S.cw.materialCatalog || [], max = Math.max(...rows.map((x) => x[1]), 1);
    return rows.map(([id, value, qty]) => {
      const e = cat[id] || ["", "Unknown material", ""];
      return `<div class="cw-mat"><div><strong title="${esc(e[1])}">${esc(e[1])}</strong><small>${esc(e[0])}${qty ? ` · ${esc(Number(qty.toFixed(2)).toLocaleString("en-US"))} ${esc(e[2] || "")}` : ""}</small></div>
        <span>${bdt(value)}</span><div class="bar"><i style="width:${Math.max(2, (value / max) * 100).toFixed(1)}%;background:${accent}"></i></div></div>`;
    }).join("");
  }
  function pageCWM() {
    const g = cwGuard(); if (g) return g;
    const v = cwView(), all = cwMaterials(v.codes, v.from, v.to), cat = S.cw.materialCatalog || [];
    NCSV.cwm = () => ["cw_materials", ["Kind", "Rank", "Material", "Description", "Unit", "Net value", "Net quantity", "Period from", "Period to"],
      ["wastage", "consumable"].flatMap((kind) => all[kind].map(([id, value, qty], i) => [kind, i + 1, (cat[id] || [])[0] || "", (cat[id] || [])[1] || "", (cat[id] || [])[2] || "", Math.round(value * 100) / 100, Math.round(qty * 100) / 100, v.from, v.to])), v.to];
    const panel = (title, kind, accent) => `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p>Top 25 of ${int(all[kind].length)} items by net value (issues less reversals) for the outlets and dates in view.</p></div></div><div class="panel-body cw-list">${cwMatRows(all[kind].slice(0, 25), accent)}</div></section>`;
    return `${cwBar(v)}<section class="panel"><div class="panel-head"><div><h2>Where the value goes</h2><p>Follows every filter and the selected dates. The CSV has every item, not just the top 25.</p></div><div class="panel-tools">${csvBtn("cwm")}</div></div></section>
      <div class="grid-h">${panel("Top wasted items", "wastage", "var(--series-3)")}${panel("Top consumable items", "consumable", "var(--series-1)")}</div>`;
  }

  // ---- outlet register
  function pageCWO() {
    const g = cwGuard(); if (g) return g;
    const v = cwView();
    const rate = (k) => ({ k, label: CWM[k].short, num: 1, fmt: (r) => `<span class="rate-pair"><strong>${cwPct(r[k])}</strong>${chip(r.statuses[k])}</span><span class="cell-secondary">Target ${cwPct(r[CWM[k].target])}</span>`, csv: (r) => csv4(r[k]) });
    const money = (k, label) => ({ k, label, num: 1, fmt: (r) => exact(r[k]), csv: (r) => Math.round((r[k] || 0) * 100) / 100 });
    const txt = (k, label) => ({ k, label, fmt: (r) => esc(r[k] || "—"), csv: (r) => r[k] || "" });
    const shown = [
      { k: "code", label: "Outlet", val: (r) => r.code, fmt: (r) => `<span class="cell-primary">${esc(r.code)}</span><span class="cell-secondary">${esc(r.name)}</span>`, csv: (r) => r.code },
      txt("regionalLeader", "Regional leader"), txt("zone", "Zonal"), txt("division", "Division"), txt("district", "District"), txt("criteria", "Final criteria"),
      money("sales", "Overall sales"), money("pnpSales", "PNP sales"), money("consumable", "Consumable"), rate("consumableRate"), money("wastage", "Wastage"), rate("wastageSalesRate"), rate("wastagePnpRate"),
      { k: "excessTotal", label: "Amount above target", num: 1, fmt: (r) => (r.excessTotal > 0 ? `<span class="down">${bdt(r.excessTotal)}</span>` : '<span class="muted">—</span>'), csv: (r) => Math.round(r.excessTotal) },
    ];
    const csvCols = [shown[0], { k: "name", label: "Outlet name", csv: (r) => r.name }, ...shown.slice(1, 6), txt("format", "Format"), txt("pnpStatus", "PNP status"), txt("ownership", "Ownership"),
      money("sales", "Overall sales"), money("pnpSales", "PNP sales (FRESH PRODUCE)"), money("consumable", "Consumable value"), money("consumableSales", "Consumable sales base"),
      { k: "consumableCutoff", label: "Consumable cut-off", csv: (r) => r.consumableCutoff || "" }, { k: "consumableRate", label: "Consumable %", csv: (r) => csv4(r.consumableRate) }, { k: "consumableTarget", label: "Consumable target %", csv: (r) => csv4(r.consumableTarget) },
      money("wastage", "Wastage value"), { k: "wastageSalesRate", label: "Wastage % on sales", csv: (r) => csv4(r.wastageSalesRate) }, { k: "wastageSalesTarget", label: "Wastage sales target %", csv: (r) => csv4(r.wastageSalesTarget) },
      { k: "wastagePnpRate", label: "Wastage % on PNP sales", csv: (r) => csv4(r.wastagePnpRate) }, { k: "wastagePnpTarget", label: "Wastage PNP target %", csv: (r) => csv4(r.wastagePnpTarget) },
      { k: "excessTotal", label: "Amount above target", csv: (r) => Math.round(r.excessTotal) }, { k: "pf", label: "Period from", csv: () => v.from }, { k: "pt", label: "Period to", csv: () => v.to }];
    const crit = S.cwCrit && v.metrics.some((r) => r.criteria === S.cwCrit) ? S.cwCrit : null;
    return `${cwBar(v)}${mountTable("cw-reg", {
      title: "Outlet performance register", file: "cw_outlets", stamp: S.cwv.to,
      banner: crit ? `<div class="drill-banner">Showing <strong>Final criteria: ${esc(crit)}</strong> within the sidebar filters. <button type="button" data-cwcrit-clear>Show all outlets</button></div>` : "",
      desc: (n) => `${int(n)} outlets after filters and search. Click a row for the outlet profile. The CSV carries every column.`,
      rows: crit ? v.metrics.filter((r) => r.criteria === crit) : v.metrics, key: (r) => r.code, defaultSort: "wastagePnpRate",
      searchText: (r) => `${r.code} ${r.name} ${r.zone} ${r.regionalLeader} ${r.division} ${r.district} ${r.criteria}`, rowAttr: cwOutletAttr, cols: shown, csvCols,
    })}`;
  }

  // ---- outlet profile
  function openCwOutlet(code) {
    const v = cwView(), r = v.metrics.find((x) => x.code === code);
    if (!r) return;
    S.lastFocus = document.activeElement;
    const series = S.cw.daily.filter((x) => x.code === code && x.date >= v.from && x.date <= v.to).sort((a, b) => a.date.localeCompare(b.date));
    const peers = v.metrics.filter((x) => x.criteria === r.criteria), zonePeers = v.metrics.filter((x) => x.zone === r.zone), ps = cwSummarize(peers);
    const rank = (k, pool) => { const s = pool.filter((x) => isNum(x[k])).sort((a, b) => b[k] - a[k]), i = s.findIndex((x) => x.code === code); return i < 0 ? "—" : `${i + 1} of ${s.length}`; };
    const spark = (k, c) => {
      const p = series.map((x) => ratio(x[CWM[k].num], x[CWM[k].den])), ok = p.filter(isNum);
      if (ok.length < 2) return '<p class="net-empty" style="padding:10px">Not enough days to chart.</p>';
      const max = Math.max(...ok) * 1.15 || 0.001, step = 480 / Math.max(1, p.length - 1);
      let started = false;
      const d = p.map((x, i) => { if (!isNum(x)) return ""; const cmd = started ? "L" : "M"; started = true; return `${cmd}${(i * step).toFixed(1)},${(96 - (x / max) * 96).toFixed(1)}`; }).filter(Boolean).join(" ");
      return `<svg viewBox="0 0 480 96" style="width:100%;height:96px" role="img" aria-label="${esc(CWM[k].label)} by day"><path d="${d}" fill="none" style="stroke:var(${c})" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
    };
    const span = dayCount(v.from, v.to), covered = r.consumableCutoff ? dayCount(v.from, r.consumableCutoff) : 0, missed = Math.max(0, span - covered);
    const mats = cwMaterials(new Set([code]), v.from, v.to, 6);
    $("#drawerTitle").textContent = `${r.code} · ${r.name}`;
    $("#drawerBody").innerHTML = `
      <p class="muted" style="margin:0">${esc([r.criteria, r.zone, r.regionalLeader, [r.district, r.division].filter(Boolean).join(", ")].filter(Boolean).join(" · "))}</p>
      <div class="stat-grid">
        <div class="stat"><small>Overall sales</small><strong>${bdt(r.sales)}</strong><div style="font-size:12px">PNP ${bdt(r.pnpSales)}</div></div>
        <div class="stat"><small>Consumable</small><strong>${bdt(r.consumable)}</strong><div style="font-size:12px">${r.consumableCutoff ? `Base ${bdt(r.consumableSales)} to ${fdate(r.consumableCutoff)}` : "Nothing posted in this period · no rate"}</div></div>
        <div class="stat"><small>Wastage</small><strong>${bdt(r.wastage)}</strong></div>
        <div class="stat"><small>Amount above target</small><strong class="${r.excessTotal > 0 ? "down" : "up"}">${r.excessTotal > 0 ? bdt(r.excessTotal) : "None"}</strong></div>
      </div>
      <div class="cw-window"><div class="hero-row"><dt>Consumable posting window</dt><dd>${covered} of ${span} days</dd></div>
        <div class="meter${covered ? "" : " cw-empty"}"><i class="good" style="width:${span ? Math.min(100, (covered / span) * 100).toFixed(1) : 0}%"></i></div>
        <div class="meter-scale"><span>${fdate(v.from)}</span><span>${fdate(v.to)}</span></div>
        <p class="muted" style="margin:6px 0 0;font-size:12px">${r.consumableCutoff ? `Sales counted to <strong>${fdate(r.consumableCutoff)}</strong>, this outlet's last consumable posting.${missed ? ` The last ${missed} day${missed === 1 ? "" : "s"} of sales are held out of the rate because nothing was posted against them.` : " Postings run to the end of the period."}` : "No consumable was posted in this period, so this outlet has no consumable rate. It is left out of the weighted result rather than counted as zero."}</p></div>
      <div><div class="section-title">Against target</div><div class="stat-grid three">${CWK.map((k) => { const t = r[CWM[k].target], st = r.statuses[k]; return `<div class="stat"><small>${esc(CWM[k].short)}</small><strong class="${st.key === "bad" ? "down" : st.key === "good" ? "up" : ""}">${cwPct(r[k])}</strong><div style="font-size:12px">Target ${cwPct(t)}${isNum(r[k]) && isNum(t) ? ` · ${pts(r[k] - t)}` : ""}${r.prior && isNum(r.prior[k]) ? `<br>${cwDelta(r[k], r.prior[k])} vs prior` : ""}</div></div>`; }).join("")}</div></div>
      <div><div class="section-title">Consumable % by day</div>${spark("consumableRate", "--series-1")}<div class="section-title" style="margin-top:10px">Wastage on PNP % by day</div>${spark("wastagePnpRate", "--series-2")}</div>
      <div><div class="section-title">Rank, worst first</div><table class="compact"><thead><tr><th>Metric</th><th class="num">Selection</th><th class="num">Zonal</th><th class="num">Criteria peers</th></tr></thead><tbody>
        ${CWK.map((k) => `<tr><td>${esc(CWM[k].short)}</td><td class="num">${rank(k, v.metrics)}</td><td class="num">${rank(k, zonePeers)}</td><td class="num">${rank(k, peers)}</td></tr>`).join("")}</tbody></table></div>
      <div><div class="section-title">Versus ${esc(r.criteria)} peers (${int(peers.length)} outlets)</div><table class="compact"><tbody>
        ${CWK.map((k) => `<tr><td>${esc(CWM[k].short)}</td><td class="num"><strong>${cwPct(r[k])}</strong></td><td class="num muted">peer group ${cwPct(ps[k])}</td><td class="num">${pts(isNum(r[k]) && isNum(ps[k]) ? r[k] - ps[k] : null)}</td></tr>`).join("")}</tbody></table></div>
      <div><div class="section-title">Top wasted items (selected period)</div><div class="cw-list">${cwMatRows(mats.wastage, "var(--series-3)")}</div></div>
      <div><div class="section-title">Top consumable items (selected period)</div><div class="cw-list">${cwMatRows(mats.consumable, "var(--series-1)")}</div></div>`;
    showDrawer();
  }

  // ---- raw rows: the source rows behind the pages, for the outlets and dates in view
  function cwRaw(kind) {
    const v = cwView(), d = S.cw, o = (c) => d.byCode.get(c) || {};
    if (kind === "daily") {
      const rows = d.daily.filter((r) => v.codes.has(r.code) && r.date >= v.from && r.date <= v.to).sort((a, b) => a.date.localeCompare(b.date) || a.code.localeCompare(b.code));
      saveCsv(`cw_raw_outlet_days_${v.from}_to`, ["Date", "Outlet code", "Outlet name", "Regional leader", "Zonal", "Division", "District", "Final criteria", "POS NSI", "PNP sales (FRESH PRODUCE)", "Consumable value", "Consumable sales base", "Wastage value"],
        rows.map((r) => { const x = o(r.code); return [r.date, r.code, x.name, x.regionalLeader, x.zone, x.division, x.district, x.criteria, r.sales, r.pnpSales, r.consumable, r.consumableSales, r.wastage]; }), v.to);
    } else {
      const cat = d.materialCatalog || [], rows = [];
      ["consumable", "wastage"].forEach((k) => d.materialDaily[k].forEach(([date, code, id, value, qty]) => {
        if (!v.codes.has(code) || date < v.from || date > v.to) return;
        const x = o(code), m = cat[id] || [];
        rows.push([date, k === "consumable" ? "Consumable" : "Wastage", code, x.name, x.regionalLeader, x.zone, m[0] || "", m[1] || "", m[2] || "", value, qty]);
      }));
      rows.sort((a, b) => a[0].localeCompare(b[0]) || a[2].localeCompare(b[2]));
      saveCsv(`cw_raw_material_postings_${v.from}_to`, ["Posting date", "Kind", "Outlet code", "Outlet name", "Regional leader", "Zonal", "Material", "Description", "Unit", "Net value", "Net quantity"], rows, v.to);
    }
  }

  // ---- data quality (shown on the Data quality page)
  function cwQualityPanel() {
    const head = `<div class="panel-head"><div><h2>Consumable and wastage files</h2><p>All five files come from the mother Drive folder, from any sub-folder. Each is recognised by its columns, so filenames and folders don't matter; sales is the same till-date file the Outlet network uses.</p></div></div>`;
    if (!S.cw) { loadCw(); return `<section class="panel">${head}<div class="panel-body"><p class="muted" style="margin:0">${S.cwErr ? `cw.json could not be loaded (${esc(S.cwErr)}).` : "Loading…"}</p></div></section>`; }
    const q = S.cw.dataQuality, w = q.consumableWindow || {}, un = q.unmappedActiveOutlets || [], rc = q.sales?.reconciliation || {}, al = q.periodAlignment || {};
    const rev = [...new Set([...(q.negativeNetConsumableOutlets || []), ...(q.negativeNetWastageOutlets || [])])], dup = q.zone?.duplicateCodes || [];
    const item = (lvl, title, body) => `<div class="issue"><span>${chip({ cls: lvl, label: lvl === "good" ? "Passed" : lvl === "bad" ? "Problem" : lvl === "warn" ? "Warning" : "Note" })}</span><div>${esc(title)}<small>${body}</small></div></div>`;
    return `<section class="panel">${head}<div class="table-wrap"><table><thead><tr><th>File</th><th>Type</th><th class="num">Rows</th><th>Covers</th></tr></thead><tbody>
      ${S.cw.sourceFiles.map((s) => `<tr><td class="cell-primary">${esc(s.name)}</td><td>${esc(s.id)}</td><td class="num">${int(s.rows)}</td><td>${s.dateMin ? `${fdate(s.dateMin)} to ${fdate(s.dateMax)}` : "—"}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel-body">
        ${item(un.length ? "warn" : "good", un.length ? "Active outlets missing from the zone master" : "All active outlets are mapped", un.length ? `${esc(un.join(", "))}. They show as Unmapped and are left out of target-weighted results only.` : "Every active outlet joined to the hierarchy master.")}
        ${item(rev.length ? "info" : "good", rev.length ? "Net movement reversals" : "No net reversal outlets", rev.length ? `${esc(rev.join(", "))}. Kept as net movement and flagged rather than zeroed.` : "Net movement values are non-negative for all outlets.")}
        ${item(dup.length ? "bad" : "good", dup.length ? "Duplicate outlet codes in the zone master" : "Zone master codes are unique", dup.length ? esc(dup.join(", ")) : `${int(q.zone?.rows)} outlets, no duplicated code.`)}
        ${(() => {
          if (al.aligned) return item("good", "Source periods line up", "Sales, consumable and wastage cover the same days.");
          const src = al.sources || {}, sEnd = src.sales?.dateMax, mEnd = [src.consumable?.dateMax, src.wastage?.dateMax].filter(Boolean).sort().pop();
          if (sEnd && mEnd && sEnd < mEnd) return item("warn", "Sales stops before the consumable and wastage postings", `Sales runs to ${fdate(sEnd)} but postings run to ${fdate(mEnd)}. Rates need sales as their base, so the dashboard shows up to ${fdate(sEnd)}; postings after that appear once a newer Sales-Till file is in the Drive folder.`);
          return item("warn", "Source periods do not line up", `${esc((al.laggingSources || []).join(", ") || "A source")} ends before sales. Consumable corrects for this through its posting window; the two wastage rates are understated. Filter to ${fdate(al.commonStart)} to ${fdate(al.commonEnd)} for a like-for-like view.`);
        })()}
        ${item((w.outletsWithoutPosting || []).length ? "info" : "good", "Consumable base counted to each outlet's last posting date", `${int(w.outletsTruncated)} of ${int(w.outletsWithPosting)} posting outlets stop before ${fdate(w.salesLastDate)}, holding back ${esc(exact(w.excludedSales))} of ${esc(exact(w.salesTotal))} sales. The full-period rate reads ${cwPct(w.rateOnPostedWindow)} instead of ${cwPct(w.rateOnFullSales)}.`)}
        ${rc.reportedTotal != null ? item(rc.matches ? "good" : "info", rc.matches ? "Sales reconciles to the file's total row" : "Sales detail differs from the file's total row", `Detail rows ${esc(exact(rc.detailTotal))} against total row ${esc(exact(rc.reportedTotal))}.`) : ""}
      </div></section>`;
  }

  function wireCw(root) {
    $$("[data-cwoutlet]", root).forEach((n) => { n.onclick = () => openCwOutlet(n.dataset.cwoutlet); n.onkeydown = (e) => { if (e.key === "Enter") openCwOutlet(n.dataset.cwoutlet); }; });
    $$("[data-cwsel]", root).forEach((s) => (s.onchange = () => { S.cwv[s.dataset.cwsel] = s.value; changed(); }));
    $$("[data-cwdate]", root).forEach((i) => (i.onchange = () => { if (i.value) { S.cwv[i.dataset.cwdate] = i.value; changed(); } }));
    $$("[data-cwquick]", root).forEach((s) => (s.onchange = () => {
      const { min, max } = S.cw.dateRange, q = s.value;
      if (!q) return;
      const from = q === "all" ? min : q === "mtd" ? max.slice(0, 8) + "01" : shiftDay(max, -(Number(q) - 1));
      S.cwv.from = from < min ? min : from; S.cwv.to = max;
      changed();
    }));
    $$("[data-cwcompare]", root).forEach((b) => (b.onclick = () => { S.cwv.compare = !S.cwv.compare; render(); }));
    $$("[data-cwraw]", root).forEach((b) => (b.onclick = () => cwRaw(b.dataset.cwraw)));
    $$("[data-cwcrit]", root).forEach((n) => { const go = () => { S.cwCrit = n.dataset.cwcrit; location.hash = "cwo"; }; n.onclick = go; n.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("[data-cwcrit-clear]", root).forEach((b) => (b.onclick = () => { S.cwCrit = null; render(); }));
  }

  // ------------------------------------------------------------------ availability
  // data/av.json is built by scripts/av/refresh.py from the mother Drive folder (SKU lists, stock,
  // 60-day sales (DOS), E-Commerce assortment, KVI outlet list, Zone Distribution). Outlets with no
  // Core/KVI/Promo stock or no Core/KVI/Promo sales are already left out by the build.
  // Pair status for the chosen days of cover:
  //   sales in the last 60 days: out of stock (stock <= 0), below cover (stock < per-day x days) or available;
  //   no sales in 60 days: available when there is stock, otherwise "no sales, no stock".
  const AV_ST = [
    { k: "ok", label: "Available", cls: "good" }, { k: "below", label: "Below cover", cls: "warn" }, { k: "oos", label: "Out of stock", cls: "bad" },
    { k: "nsin", label: "No sales, in stock", cls: "info" }, { k: "nsout", label: "No sales, no stock", cls: "bad" },
  ];
  const AV_OK = [true, false, false, true, false];
  const AV_TYPES = [["all", "Core, Promo and KVI"], ["core", "Core"], ["promo", "Promo"], ["kvi", "KVI"]];
  const AV_DAYS = [["1", "1 day"], ["2", "2 days"], ["3", "3 days"], ["5", "5 days"], ["7", "7 days"]];
  const avStatus = (st, sl, days) => (!(sl > 0) ? (st > 0 ? 3 : 4) : st <= 0 ? 2 : st >= (sl / 60) * days ? 0 : 1);
  const avAcc = () => ({ slots: 0, ok: 0, st: [0, 0, 0, 0, 0], stock: 0, perDay: 0, short: 0 });
  function avAdd(a, st, sl, days, s) {
    a.slots++; a.st[s]++; if (AV_OK[s]) a.ok++;
    a.stock += st;
    if (sl > 0) { const pd = sl / 60; a.perDay += pd; a.short += Math.max(0, pd * days - st); }
  }
  const avRate = (a) => (a.slots ? a.ok / a.slots : null);

  function loadAv() {
    if (S.av || S.avLoading) return;
    S.avLoading = true; S.avErr = null;
    fetch("data/av.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => { prepAv(d); S.av = d; })
      .catch((e) => { S.avErr = e.message; })
      .finally(() => { S.avLoading = false; if (AV_PAGES.has(S.page) || S.page === "dq") render(); });
  }
  function prepAv(d) {
    const v = (x) => (x == null || String(x).trim() === "" ? NET_MISS : String(x).trim());
    d.outlets.forEach((o, i) => { o.i = i; o.nm = o.n; o.dim = { rl: v(o.rl), zn: v(o.zn), div: v(o.div), dis: v(o.dis), fmt: v(o.fmt), own: v(o.own), pnp: v(o.pnp), loc: v(o.loc), area: v(o.area) }; });
    d.skus.forEach((s, i) => (s.i = i));
    d.S = d.skus.length;
    d.stock = Float64Array.from(d.stock); d.sales60 = Float64Array.from(d.sales60);
    d.byCode = new Map(d.outlets.map((o) => [o.c, o]));
    d.skuByCode = new Map(d.skus.map((s) => [s.c, s]));
    d.ecom.skus.forEach((s, i) => (s.i = i));
    const now = Date.now();
    // Stock and DOS update daily: flag either one when it is more than 2 days old.
    d.stale = d.files.filter((f) => (f.kind === "stock" || f.kind === "dos") && f.modified && now - Date.parse(f.modified) > 2 * 86400000);
  }
  function avGuard() {
    if (S.av) return "";
    loadAv();
    return S.avErr ? `<p class="empty">The availability data could not be loaded (${esc(S.avErr)}). Run the "Refresh data" workflow on GitHub, then reload this page.</p>` : '<p class="empty">Loading availability data…</p>';
  }
  const avDays = () => Number(S.avv.days) || 2;
  function avSkus(type) {
    const f = S.avv;
    return S.av.skus.filter((s) => (type === "all" ? s.core || s.promo || s.kvi : s[type]) && (!f.nd || s.nd === f.nd) && (!f.cat3 || s.cat3 === f.cat3));
  }
  const avOutlets = (kviOnly) => inView().filter((o) => !kviOnly || o.kvi);
  // One pass over the pairs in view: totals, per outlet and per SKU.
  function avScan(type, kviOnly) {
    const d = S.av, days = avDays(), skus = avSkus(type), outs = avOutlets(kviOnly), N = d.S;
    const tot = avAcc(), byO = new Map(), byS = new Map(skus.map((s) => [s.i, avAcc()]));
    for (const o of outs) {
      const a = avAcc(), base = o.i * N;
      for (const s of skus) {
        const st = d.stock[base + s.i], sl = d.sales60[base + s.i], k = avStatus(st, sl, days);
        avAdd(a, st, sl, days, k); avAdd(byS.get(s.i), st, sl, days, k);
      }
      byO.set(o.i, a);
      tot.slots += a.slots; tot.ok += a.ok; a.st.forEach((x, i) => (tot.st[i] += x)); tot.stock += a.stock; tot.perDay += a.perDay; tot.short += a.short;
    }
    return { type, tot, byO, byS, outs, skus };
  }
  // E-Commerce pairs (Assortment = YES only): available when stock >= DOS 2 Days.
  const avEcomStatus = (st, d2) => (d2 > 0 ? (st <= 0 ? 2 : st >= d2 ? 0 : 1) : st > 0 ? 3 : 4);
  function avEcomScan() {
    const d = S.av, f = S.avv, keep = new Set(inView().map((o) => o.i));
    const okSku = d.ecom.skus.map((s) => (!f.nd || s.nd === f.nd) && (!f.cat3 || s.cat3 === f.cat3));
    const tot = avAcc(), byO = new Map(), byS = new Map();
    for (const [oi, si, st, d2, mon] of d.ecom.pairs) {
      if (!keep.has(oi) || !okSku[si]) continue;
      const k = avEcomStatus(st, d2);
      const add = (a) => { a.slots++; a.st[k]++; if (AV_OK[k]) a.ok++; a.stock += st; a.perDay += (mon || 0) / 30; a.short += Math.max(0, d2 - st); };
      add(tot);
      if (!byO.has(oi)) byO.set(oi, avAcc()); add(byO.get(oi));
      if (!byS.has(si)) byS.set(si, avAcc()); add(byS.get(si));
    }
    return { tot, byO, byS };
  }

  // ---- shared parts
  const avSel = (key, opts, label) => `<select class="sel" data-avsel="${key}" aria-label="${esc(label)}">${opts.map(([v, t]) => `<option value="${esc(v)}" ${String(S.avv[key]) === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  const avSeg = (key, opts, label) => `<div class="seg" role="group" aria-label="${esc(label)}">${opts.map(([v, t]) => `<button data-avset="${key}" data-val="${esc(v)}" aria-pressed="${String(S.avv[key]) === String(v)}">${esc(t)}</button>`).join("")}</div>`;
  function avBar(extra = "", ecom = false) {
    const d = S.av, f = S.avv;
    const pool = ecom ? d.ecom.skus : d.skus.filter((s) => s.core || s.promo || s.kvi);
    const nds = [...new Set(pool.map((s) => s.nd).filter(Boolean))].sort();
    const cats = [...new Set(pool.filter((s) => !f.nd || s.nd === f.nd).map((s) => s.cat3).filter(Boolean))].sort();
    const stale = d.stale.length ? `<p class="note" style="margin:0">${d.stale.map((x) => `${x.kind === "stock" ? "Stock" : "Sales (DOS)"} file is from ${fdate(x.modified.slice(0, 10))}`).join("; ")}, more than 2 days old. Upload today's file to the Availability folder.</p>` : "";
    if (!UI.avBarOpen) {
      const parts = [ecom ? "Stock against DOS 2 Days" : `${avDays()} day${avDays() === 1 ? "" : "s"} of cover`, f.nd || "All product divisions", f.cat3 || "All CAT3"];
      return `<section class="panel ui-slim"><div class="panel-head"><div><h2>Scope</h2><p>${esc(parts.join(" · "))}</p></div>
        <div class="panel-tools">${extra}<button class="btn" data-uitoggle="avBarOpen" aria-expanded="false">Show</button></div></div>${stale ? `<div class="panel-body">${stale}</div>` : ""}</section>`;
    }
    return `<section class="panel"><div class="panel-head"><div><h2>Scope</h2><p>${ecom ? "E-Commerce: available when stock covers DOS 2 Days; only Assortment = YES pairs count." : `Available when stock covers the chosen days of sales (60-day sales ÷ 60 × days). Items with no sales in 60 days count as available when in stock.`} ${int(d.excluded.length)} outlets with no Core, KVI or Promo stock or sales are left out everywhere.</p></div>
      <div class="panel-tools">${ecom ? "" : `<label class="net-date">Required cover${avSel("days", AV_DAYS, "Required cover")}</label>`}
        ${avSel("nd", [["", "All product divisions"], ...nds.map((x) => [x, x])], "Product division")}
        ${avSel("cat3", [["", "All CAT3"], ...cats.map((x) => [x, x])], "CAT3")}${extra}<button class="btn" data-uitoggle="avBarOpen" aria-expanded="true">Hide</button></div></div>${stale ? `<div class="panel-body">${stale}</div>` : ""}</section>`;
  }
  const avPct = (a) => (a && a.slots ? pct(avRate(a), 2) : "—");
  // Status chips use the same five bands as the criteria cards (AV_BANDS).
  const avBand = (r) => (!isNum(r) ? { cls: "idle", label: "No items" } : { cls: ["good", "info", "warn", "bad", "crit"][avBandIdx(r)], label: AV_BANDS[avBandIdx(r)] });
  function avCard(label, a, accent, sub) {
    const r = avRate(a);
    return kpi({ label, value: avPct(a), accent, sub: `${chip(avBand(r))}<span>${int(a.ok)} of ${int(a.slots)} available</span>`, foot: sub || `<span>Out of stock ${int(a.st[2])}</span><span>Below cover ${int(a.st[1])}</span>` });
  }
  function avStrip(a) {
    return `<div class="stat-strip net-strip" style="border-top:1px solid var(--line-soft)">${AV_ST.map((s, i) => `<div><span>${chip(s)}</span><strong>${int(a.st[i])}</strong><small>${a.slots ? pct(a.st[i] / a.slots, 1) : "—"} of pairs</small></div>`).join("")}</div>`;
  }
  // Columns shared by every availability table.
  function avCols(first, countLabel) {
    return [first, ...(countLabel ? [{ k: "n", label: countLabel, num: 1, fmt: (x) => int(x.n) }] : []),
      { k: "slots", label: "Pairs", num: 1, fmt: (x) => int(x.slots), hide: 1 },
      { k: "ok", label: "Available", num: 1, fmt: (x) => int(x.ok) },
      { k: "rate", label: "Availability", num: 1, firstDir: "asc", val: (x) => avRate(x), fmt: (x) => `<span class="rate-pair"><strong>${avPct(x)}</strong>${chip(avBand(avRate(x)))}</span>`, csv: (x) => (isNum(avRate(x)) ? (avRate(x) * 100).toFixed(2) : "") },
      { k: "oos", label: "Out of stock", num: 1, val: (x) => x.st[2], fmt: (x) => int(x.st[2]), csv: (x) => x.st[2] },
      { k: "below", label: "Below cover", num: 1, val: (x) => x.st[1], fmt: (x) => int(x.st[1]), csv: (x) => x.st[1], hide: 1 },
      { k: "nsin", label: "No sales, in stock", num: 1, val: (x) => x.st[3], fmt: (x) => int(x.st[3]), csv: (x) => x.st[3], hide: 1 },
      { k: "nsout", label: "No sales, no stock", num: 1, val: (x) => x.st[4], fmt: (x) => int(x.st[4]), csv: (x) => x.st[4], hide: 1 },
      { k: "stock", label: "Stock (units)", num: 1, fmt: (x) => int(x.stock), csv: (x) => Math.round(x.stock), hide: 1 },
      { k: "perDay", label: "Sales per day", num: 1, fmt: (x) => int(x.perDay), csv: (x) => x.perDay.toFixed(2), hide: 1 },
      { k: "short", label: "Shortfall (units)", num: 1, fmt: (x) => (x.short ? `<span class="down">${int(x.short)}</span>` : "0"), csv: (x) => Math.round(x.short), hide: 1 }];
  }
  const avOutletFirst = { k: "name", label: "Outlet", val: (x) => x.name, fmt: (x) => `<span class="cell-primary">${esc(x.code)} · ${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span>`, csv: (x) => `${x.code} ${x.name}` };
  const avSkuFirst = { k: "name", label: "SKU", val: (x) => x.name, fmt: (x) => `<span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.code)} · ${esc(x.sub)}</span>`, csv: (x) => `${x.code} ${x.name}` };
  const avTypeChips = (s) => ["core", "promo", "kvi"].filter((t) => s[t]).map((t) => t.toUpperCase()).join(", ");
  const avOutletRows = (scan) => scan.outs.map((o) => ({ ...scan.byO.get(o.i), code: o.c, name: o.n, sub: `${avUnassigned(o.dim.zn)} · ${avUnassigned(o.dim.rl)}`, o })).filter((x) => x.slots);
  const avSkuRows = (scan) => scan.skus.map((s) => ({ ...scan.byS.get(s.i), code: s.c, name: s.n, sub: `${s.nd || "—"} · ${s.cat3 || "—"} · ${avTypeChips(s)}`, s, n: scan.outs.length })).filter((x) => x.slots);
  function avOutletTable(id, scan, title, type, pageSize) {
    return mountTable(id, { title, file: `availability_${id}`, stamp: S.av.generatedAt.slice(0, 10), pageSize: pageSize || 50,
      desc: (n) => `${int(n)} outlets, lowest availability first. Click an outlet for the items it is missing.`,
      rows: avOutletRows(scan), key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "rate", defaultDir: "asc",
      rowAttr: (x) => `data-avoutlet="${esc(x.code)}" data-avtype="${type}" tabindex="0"`, cols: avCols(avOutletFirst) });
  }
  function avSkuTable(id, scan, title, type, pageSize, tools) {
    return mountTable(id, { title, file: `availability_${id}`, stamp: S.av.generatedAt.slice(0, 10), pageSize: pageSize || 50, tools,
      desc: (n) => `${int(n)} SKUs across ${int(scan.outs.length)} outlets, lowest availability first. Click a SKU for the outlets missing it.`,
      rows: avSkuRows(scan), key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "rate", defaultDir: "asc",
      rowAttr: (x) => `data-avsku="${esc(x.code)}" data-avtype="${type}" tabindex="0"`, cols: avCols(avSkuFirst, "Outlets") });
  }
  // Grouped table (Product division, CAT3, Zonal, Regional leader). Clicking a group lists its outlets or SKUs.
  const AV_LEVELS = { nd: "Product division", cat3: "CAT3", zn: "Zonal", rl: "RHO", outlet: "Outlet" };
  function avGroupTable(id, scan, level, type, tools = "") {
    const gd = gdrill(id, level);
    if (level === "outlet" || (gd && (level === "zn" || level === "rl"))) {
      const sc = gd ? { ...scan, outs: scan.outs.filter((o) => o.dim[level] === gd.key) } : scan;
      return mountTable(id, { title: gd ? `Outlets of ${avUnassigned(gd.key)}` : "Availability by outlet", file: `availability_${id}_outlet`, stamp: S.av.generatedAt.slice(0, 10), banner: gBanner(id, gd), tools: gd ? "" : tools,
        desc: (n) => `${int(n)} outlets, lowest availability first. Click an outlet for the items it is missing.`,
        rows: avOutletRows(sc), key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "rate", defaultDir: "asc",
        rowAttr: (x) => `data-avoutlet="${esc(x.code)}" data-avtype="${type}" tabindex="0"`, cols: avCols(avOutletFirst) });
    }
    if (gd) { // product division or CAT3: list its SKUs
      const sc = { ...scan, skus: scan.skus.filter((s) => (s[level] || "—") === gd.key) };
      return mountTable(id, { title: `SKUs in ${gd.key}`, file: `availability_${id}_sku`, stamp: S.av.generatedAt.slice(0, 10), banner: gBanner(id, gd),
        desc: (n) => `${int(n)} SKUs, lowest availability first. Click a SKU for the outlets missing it.`,
        rows: avSkuRows(sc), key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "rate", defaultDir: "asc",
        rowAttr: (x) => `data-avsku="${esc(x.code)}" data-avtype="${type}" tabindex="0"`, cols: avCols(avSkuFirst, "Outlets") });
    }
    const g = new Map(), bySku = level === "nd" || level === "cat3";
    const put = (key, a, what) => { const x = g.get(key) || { ...avAcc(), key, name: key, n: 0 }; x.slots += a.slots; x.ok += a.ok; a.st.forEach((v, i) => (x.st[i] += v)); x.stock += a.stock; x.perDay += a.perDay; x.short += a.short; x.n++; x.what = what; g.set(key, x); };
    if (bySku) scan.skus.forEach((s) => put(s[level] || "—", scan.byS.get(s.i), "SKUs"));
    else scan.outs.forEach((o) => put(o.dim[level], scan.byO.get(o.i), "outlets"));
    const rows = [...g.values()].filter((x) => x.slots);
    return mountTable(id, { title: `Availability by ${level === "rl" || level === "cat3" ? AV_LEVELS[level] : AV_LEVELS[level].toLowerCase()}`, file: `availability_${id}_${level}`, stamp: S.av.generatedAt.slice(0, 10), tools,
      desc: (n) => `${int(n)} groups, lowest availability first. Group figures are sums of their pairs. Click a group to list its ${bySku ? "SKUs" : "outlets"}.`,
      rows, key: (x) => x.key, searchText: (x) => x.name, defaultSort: "rate", defaultDir: "asc",
      rowAttr: (x) => `data-gpick="${id}" data-glevel="${level}" data-gkey="${esc(x.key)}" tabindex="0" title="List ${esc(x.name)}'s ${bySku ? "SKUs" : "outlets"}"`,
      cols: avCols({ k: "name", label: AV_LEVELS[level], val: (x) => x.name, fmt: (x) => `<span class="cell-primary">${esc(avUnassigned(x.name))}</span>`, csv: (x) => avUnassigned(x.name) }, bySku ? "SKUs" : "Outlets") });
  }

  // RHO wise overall availability: per regional leader, the average of their outlets' own availability
  // for Core, Promo, KVI and all three together, and how many outlets fall in each band.
  const AV_BANDS = ["91%-100%", "81%-90%", "71%-80%", "61%-70%", "60% or below"];
  const AV_BAND_CLS = ["b1", "b2", "b3", "b4", "b5"];
  // Availability criteria card: name, subtitle, average outlet availability, a bar split into the bands and the
  // band counts. head / band(i) return the click attributes for the title and for each band.
  function avCriteriaCard(c, wide) {
    const pc = (v) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
    const n = c.bands.reduce((x, y) => x + y, 0) || 1, cls = isNum(c.avg) ? AV_BAND_CLS[avBandIdx(c.avg)] : "";
    const pr = c.pairs ? avRate(c.pairs) : null, pcls = isNum(pr) ? AV_BAND_CLS[avBandIdx(pr)] : "";
    const figure = c.pairs
      ? `<div class="av-card-val ${pcls}">${avPct(c.pairs)}</div><div class="av-card-note">available · ${int(c.pairs.ok)} of ${int(c.pairs.slots)} ${c.pairsLabel || "outlet × SKU pairs"}</div>
         <div class="av-card-avg"><span>Average outlet availability</span><b class="${cls}">${pc(c.avg)}</b></div>`
      : `<div class="av-card-val ${cls}">${pc(c.avg)}</div><div class="av-card-note">average outlet availability</div>`;
    return `<article class="av-card${wide ? " wide" : ""}">
      <div class="av-card-main"><button type="button" class="av-card-head" ${c.head} title="All ${esc(c.name)} outlets and items"><span class="av-card-name">${esc(c.name)}</span><span class="av-card-sub">${c.sub}</span></button>
        ${figure}</div>
      <div class="av-card-dist"><div class="av-stack" role="img" aria-label="${esc(AV_BANDS.map((t, i) => `${t}: ${c.bands[i]} outlets`).join(", "))}">${c.bands.map((v, i) => (v ? `<i class="${AV_BAND_CLS[i]}" style="flex-grow:${v}" title="${AV_BANDS[i]}: ${int(v)} outlets (${Math.round((v / n) * 100)}%)"></i>` : "")).join("")}</div>
        <ul class="av-bands">${AV_BANDS.map((t, i) => `<li${c.bands[i] ? ` ${c.band(i)} tabindex="0" role="button" title="${esc(c.name)} outlets at ${t}"` : ' class="zero"'}><i class="${AV_BAND_CLS[i]}"></i><span>${t}</span><b>${int(c.bands[i])}</b>${wide ? `<small>${Math.round((c.bands[i] / n) * 100)}%</small>` : ""}</li>`).join("")}</ul></div>
    </article>`;
  }
  const avBandIdx = (r) => { const x = Math.round(r * 100); return x >= 91 ? 0 : x >= 81 ? 1 : x >= 71 ? 2 : x >= 61 ? 3 : 4; };
  const AV_KINDS = [["core", "Core"], ["promo", "Promo"], ["kvi", "KVI"], ["all", "Overall"]];
  // Outlets missing from Zone Distribution (the build labels them "Not in outlet master") read as Unassigned.
  const avIsMiss = (v) => v === NET_MISS || v === "Not in outlet master";
  const avUnassigned = (v) => (avIsMiss(v) ? "Unassigned" : v);
  function avRhoStats(outs, scans) {
    const x = { n: outs.length };
    AV_KINDS.forEach(([k]) => {
      const rates = outs.map((o) => avRate(scans[k].byO.get(o.i) || avAcc())).filter(isNum);
      x[k] = rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : null;
      x[k + "B"] = [0, 0, 0, 0, 0];
      rates.forEach((r) => x[k + "B"][avBandIdx(r)]++);
    });
    return x;
  }
  function avRhoMatrix(scans) {
    const id = "av-rho", gd = gdrill(id, "rl"), outs = scans.all.outs;
    if (gd) {
      const rows = outs.filter((o) => o.dim.rl === gd.key).map((o) => {
        const r = { code: o.c, name: o.n, sub: `${avUnassigned(o.dim.zn)} · ${o.dim.fmt}`, o, oos: (scans.all.byO.get(o.i) || avAcc()).st[2] };
        AV_KINDS.forEach(([k]) => (r[k] = avRate(scans[k].byO.get(o.i) || avAcc())));
        return r;
      });
      const pc = (k, label) => ({ k, label, num: 1, firstDir: "asc", fmt: (x) => `<span class="rate-pair"><strong>${pct(x[k], 1)}</strong>${chip(avBand(x[k]))}</span>`, csv: (x) => (isNum(x[k]) ? (x[k] * 100).toFixed(2) : "") });
      return mountTable("av-rho-o", { title: `${avUnassigned(gd.key)}: outlet wise availability`, file: `availability_outlets_${gd.key}`, stamp: S.av.generatedAt.slice(0, 10), banner: gBanner(id, gd),
        desc: (n) => `${int(n)} outlets, lowest overall first. Click an outlet for the items it is missing.`,
        rows, key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "all", defaultDir: "asc",
        rowAttr: (x) => `data-avoutlet="${esc(x.code)}" data-avtype="all" tabindex="0"`,
        cols: [avOutletFirst, pc("core", "Core"), pc("promo", "Promo"), pc("kvi", "KVI"), pc("all", "Overall"), { k: "oos", label: "Out of stock items", num: 1, fmt: (x) => int(x.oos) }] });
    }
    const by = new Map();
    outs.forEach((o) => { if (!by.has(o.dim.rl)) by.set(o.dim.rl, []); by.get(o.dim.rl).push(o); });
    // Largest portfolio first; Unassigned last.
    const groups = [...by].map(([name, os]) => ({ name, ...avRhoStats(os, scans) })).sort((a, b) => avIsMiss(a.name) - avIsMiss(b.name) || b.n - a.n);
    const total = { name: "Total", ...avRhoStats(outs, scans) };
    const pc = (v) => (isNum(v) ? `${Math.round(v * 100)}%` : "—");
    const cells = (x) => `<td class="num">${int(x.n)}</td>${["core", "promo", "kvi"].map((k) => `<td class="num av-g-${k}">${pc(x[k])}</td>`).join("")}
      ${AV_KINDS.map(([k]) => `<td class="num av-g-${k} av-sep"><strong>${pc(x[k])}</strong></td>${x[k + "B"].map((c, i) => `<td class="num${i >= 2 ? " av-red" : ` av-g-${k}`}${i >= 2 && c ? " has" : ""}">${int(c)}</td>`).join("")}`).join("")}`;
    NCSV.avrho = () => ["availability_rho_wise", ["RHO", "Outlet Qty", "Core Avg %", "Promo Avg %", "KVI Avg %", ...AV_KINDS.flatMap(([, l]) => [`${l} Avg %`, ...AV_BANDS.map((b) => `${l} ${b}`)])],
      [...groups, total].map((x) => [avUnassigned(x.name), x.n, ...["core", "promo", "kvi"].map((k) => (isNum(x[k]) ? (x[k] * 100).toFixed(2) : "")), ...AV_KINDS.flatMap(([k]) => [isNum(x[k]) ? (x[k] * 100).toFixed(2) : "", ...x[k + "B"]])]), S.av.generatedAt.slice(0, 10)];
    return `<section class="panel"><div class="panel-head"><div><h2>RHO wise overall availability</h2><p>Avg % is the average of each outlet's own availability at ${avDays()} day${avDays() === 1 ? "" : "s"} of cover; the band columns count outlets. Click a regional leader for their outlets.</p></div><div class="panel-tools">${csvBtn("avrho")}</div></div>
      <div class="table-wrap av-rho"><table><thead>
        <tr><th rowspan="2">RHO</th><th rowspan="2" class="num">Outlet Qty</th><th class="num av-g-core">Core</th><th class="num av-g-promo">Promo</th><th class="num av-g-kvi">KVI</th>
          ${AV_KINDS.map(([k, l]) => `<th colspan="6" class="av-g-${k} av-sep av-grp">${l.toUpperCase()}</th>`).join("")}</tr>
        <tr><th class="num av-g-core">Avg %</th><th class="num av-g-promo">Avg %</th><th class="num av-g-kvi">Avg %</th>
          ${AV_KINDS.map(([k]) => `<th class="num av-g-${k} av-sep">Avg %</th>${AV_BANDS.map((b, i) => `<th class="num${i >= 2 ? " av-red" : ` av-g-${k}`}">${b}</th>`).join("")}`).join("")}</tr>
      </thead><tbody>
        ${groups.map((x) => `<tr data-gpick="${id}" data-glevel="rl" data-gkey="${esc(x.name)}" tabindex="0" title="List ${esc(avUnassigned(x.name))}'s outlets"><td class="cell-primary">${esc(avUnassigned(x.name))}</td>${cells(x)}</tr>`).join("")}
        <tr class="av-total"><td class="cell-primary">Total</td>${cells(total)}</tr>
      </tbody></table></div></section>`;
  }

  // Availability criteria by product division (outlet bands) and by CAT3 (Core, KVI, Promo). Every figure is
  // the average of each outlet's own availability within that division or CAT3, as in the RHO matrix.
  function avCriteria(scan) {
    const d = S.av, days = avDays(), N = d.S, outs = scan.outs, skus = scan.skus;
    const nds = [...new Set(skus.map((x) => x.nd || "—"))].sort(), c3s = [...new Set(skus.map((x) => x.cat3 || "—"))];
    const ndI = new Map(nds.map((x, i) => [x, i])), c3I = new Map(c3s.map((x, i) => [x, i])), TY = ["core", "kvi", "promo"];
    const ND = nds.length, C3 = c3s.length;
    const ndOk = new Float64Array(ND), ndSl = new Float64Array(ND), cOk = new Float64Array(C3 * 3), cSl = new Float64Array(C3 * 3);
    const ndSum = new Float64Array(ND), ndN = new Float64Array(ND), ndBand = nds.map(() => [0, 0, 0, 0, 0]);
    const cSum = new Float64Array(C3 * 3), cN = new Float64Array(C3 * 3);
    const skuNd = skus.map((x) => ndI.get(x.nd || "—")), skuC3 = skus.map((x) => c3I.get(x.cat3 || "—"));
    for (const o of outs) {
      ndOk.fill(0); ndSl.fill(0); cOk.fill(0); cSl.fill(0);
      const base = o.i * N;
      skus.forEach((x, j) => {
        const ok = AV_OK[avStatus(d.stock[base + x.i], d.sales60[base + x.i], days)] ? 1 : 0;
        ndSl[skuNd[j]]++; ndOk[skuNd[j]] += ok;
        TY.forEach((t, ti) => { if (x[t]) { const q = skuC3[j] * 3 + ti; cSl[q]++; cOk[q] += ok; } });
      });
      for (let i = 0; i < ND; i++) if (ndSl[i]) { const r = ndOk[i] / ndSl[i]; ndSum[i] += r; ndN[i]++; ndBand[i][avBandIdx(r)]++; }
      for (let q = 0; q < C3 * 3; q++) if (cSl[q]) { cSum[q] += cOk[q] / cSl[q]; cN[q]++; }
    }
    const divRows = nds.map((nd, i) => ({ nd, skus: skus.filter((x) => (x.nd || "—") === nd).length, avg: ndN[i] ? ndSum[i] / ndN[i] : null, bands: ndBand[i] }));
    const catRows = c3s.map((c, i) => { const v = TY.map((_, ti) => (cN[i * 3 + ti] ? cSum[i * 3 + ti] / cN[i * 3 + ti] : null)); return { c, core: v[0], kvi: v[1], promo: v[2], low: Math.min(...v.filter(isNum)) }; })
      .sort((a, b) => a.low - b.low || a.c.localeCompare(b.c));
    const pc = (v) => (isNum(v) ? `${Math.round(v * 100)}%` : "");
    const red = (v) => (isNum(v) && v < 0.7 ? " av-low" : "");
    const stamp = d.generatedAt.slice(0, 10);
    NCSV.avdiv = () => ["availability_by_new_division", ["New Division", "SKUs", "Avg %", ...AV_BANDS], divRows.map((x) => [x.nd, x.skus, isNum(x.avg) ? (x.avg * 100).toFixed(2) : "", ...x.bands]), stamp];
    NCSV.avcat = () => ["availability_by_cat3", ["CAT3", "Core %", "KVI %", "Promo %"], catRows.map((x) => [x.c, ...["core", "kvi", "promo"].map((t) => (isNum(x[t]) ? (x[t] * 100).toFixed(2) : ""))]), stamp];
    return `<div class="grid-h av-crit">
      <section class="panel"><div class="panel-head"><div><h2>Availability criteria (New Division)</h2><p>Average of outlet availability for each division, and how many outlets fall in each band. Click a card or a band for its items and outlets.</p></div><div class="panel-tools">${csvBtn("avdiv")}</div></div>
        <div class="panel-body"><div class="av-cards div">${divRows.map((x) => avCriteriaCard({ name: x.nd, sub: `${int(x.skus)} SKUs · ${int(x.bands.reduce((a, b) => a + b, 0))} outlets`, avg: x.avg, bands: x.bands,
          head: `data-avgrp="nd" data-avkey="${esc(x.nd)}"`, band: (i) => `data-avgrp="nd" data-avkey="${esc(x.nd)}" data-avband="${i}"` })).join("")}</div></div></section>
      <section class="panel"><div class="panel-head"><div><h2>Availability criteria (CAT3)</h2><p>Weakest first. Red is below 70%; blank means no SKU of that type in the CAT3. Click a figure for its items and outlets.</p></div><div class="panel-tools">${csvBtn("avcat")}</div></div>
        <div class="table-wrap"><table><thead><tr><th>Availability criteria (CAT3)</th><th class="num">Core %</th><th class="num">KVI %</th><th class="num">Promo %</th></tr></thead><tbody>
        ${catRows.map((x) => `<tr><td>${esc(x.c)}</td>${["core", "kvi", "promo"].map((t) => (isNum(x[t]) ? `<td class="num av-click${red(x[t])}" data-avgrp="cat3" data-avkey="${esc(x.c)}" data-avtypekey="${t}" tabindex="0" title="${esc(x.c)} ${t.toUpperCase()}: items and outlets">${pc(x[t])}</td>` : "<td></td>")).join("")}</tr>`).join("")}
        </tbody></table></div></section></div>`;
  }

  // Drawer for a division (optionally one outlet band of it) or a CAT3 + type: its items and its outlets.
  function openAvGroup(level, key, band, type, kviOnly) {
    const d = S.av, days = avDays(), N = d.S;
    const skus = avSkus(type || "all").filter((x) => level === "type" || (x[level] || "—") === key);
    const outs = avOutlets(kviOnly);
    const sAcc = new Map(skus.map((x) => [x.i, avAcc()])), oRows = [];
    for (const o of outs) {
      const a = avAcc(), base = o.i * N;
      for (const x of skus) {
        const st = d.stock[base + x.i], sl = d.sales60[base + x.i], k = avStatus(st, sl, days);
        avAdd(a, st, sl, days, k); avAdd(sAcc.get(x.i), st, sl, days, k);
      }
      if (a.slots && (band == null || avBandIdx(avRate(a)) === band)) oRows.push({ o, a });
    }
    // Item figures follow the outlets listed, so a band's drawer shows items at those outlets only.
    if (band != null) {
      sAcc.forEach((v, k) => sAcc.set(k, avAcc()));
      for (const { o } of oRows) for (const x of skus) { const st = d.stock[o.i * N + x.i], sl = d.sales60[o.i * N + x.i]; avAdd(sAcc.get(x.i), st, sl, days, avStatus(st, sl, days)); }
    }
    const tot = avAcc();
    oRows.forEach(({ a }) => { tot.slots += a.slots; tot.ok += a.ok; a.st.forEach((v, i) => (tot.st[i] += v)); });
    const items = skus.map((x) => ({ x, a: sAcc.get(x.i) })).filter((r) => r.a.slots).sort((p, q) => avRate(p.a) - avRate(q.a));
    oRows.sort((p, q) => avRate(p.a) - avRate(q.a));
    S.lastFocus = document.activeElement;
    const what = level === "type" ? (type === "all" ? "Over all (Core, Promo and KVI)" : type.toUpperCase()) : level === "nd" ? key : `${key} · ${type.toUpperCase()}`;
    $("#drawerTitle").textContent = band != null ? `${what}: outlets at ${AV_BANDS[band]}` : what;
    const tr = (attr, name, sub, a) => `<tr ${attr} tabindex="0" style="cursor:pointer"><td><span class="cell-primary">${esc(name)}</span><span class="cell-secondary">${esc(sub)}</span></td><td class="num"><strong>${avPct(a)}</strong></td><td class="num">${int(a.ok)} / ${int(a.slots)}</td><td class="num">${int(a.st[2])}</td></tr>`;
    const head = (first) => `<thead><tr><th>${first}</th><th class="num">Availability</th><th class="num">Available</th><th class="num">Out of stock</th></tr></thead>`;
    $("#drawerBody").innerHTML = `<div class="stat-grid three"><div class="stat"><small>Availability</small><strong>${avPct(tot)}</strong><div style="font-size:12px">${int(tot.ok)} of ${int(tot.slots)} pairs</div></div>
        <div class="stat"><small>Items</small><strong>${int(items.length)}</strong><div style="font-size:12px">${type && type !== "all" ? type.toUpperCase() : "Core, Promo and KVI"}</div></div>
        <div class="stat"><small>Outlets</small><strong>${int(oRows.length)}</strong><div style="font-size:12px">${band != null ? AV_BANDS[band] : "in view"}</div></div></div>
      <div><div class="section-title">Items, lowest availability first${band != null ? " (at these outlets)" : ""}</div><div class="table-wrap" style="max-height:340px"><table class="compact">${head("Item")}<tbody>
        ${items.map(({ x, a }) => tr(`data-avsku="${esc(x.c)}" data-avtype="${type || "all"}"`, x.n, `${x.c} · ${x.cat3 || "—"} · ${avTypeChips(x)}`, a)).join("")}</tbody></table></div></div>
      <div><div class="section-title">Outlets, lowest availability first</div><div class="table-wrap" style="max-height:420px"><table class="compact">${head("Outlet")}<tbody>
        ${oRows.map(({ o, a }) => tr(`data-avoutlet="${esc(o.c)}" data-avtype="${type || "all"}"`, `${o.c} · ${o.n}`, `${avUnassigned(o.dim.zn)} · ${avUnassigned(o.dim.rl)}`, a)).join("") || '<tr><td colspan="4" class="empty">No outlets.</td></tr>'}</tbody></table></div></div>`;
    wireAv($("#drawerBody"));
    showDrawer();
  }

  // Availability criteria by SKU type: SKU count, average outlet availability and outlets per band.
  // kinds: any of core / promo / kvi / all (over all, unique SKUs) / ecom.
  function avTypeCriteria(kinds, scans, kviOnly) {
    const label = { core: "Core", promo: "Promo", kvi: "KVI", all: "Over All (Unique SKU)" };
    const blocks = kinds.map((k) => {
      if (k === "ecom") {
        const e = scans.ecom, rates = [...e.byO.values()].map(avRate).filter(isNum), bands = [0, 0, 0, 0, 0];
        rates.forEach((r) => bands[avBandIdx(r)]++);
        return { k, title: `Ecom Availability (${int(e.byS.size)} SKU / ${int(e.byO.size)} Outlet)`, avg: rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : null, bands };
      }
      const sc = scans[k], rates = sc.outs.map((o) => avRate(sc.byO.get(o.i) || avAcc())).filter(isNum), bands = [0, 0, 0, 0, 0];
      rates.forEach((r) => bands[avBandIdx(r)]++);
      return { k, title: `${label[k]} (${int(sc.skus.length)} SKU)`, avg: rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : null, bands };
    });
    const kvi = kviOnly ? ' data-avkvi="yes"' : "";
    const attr = (b, i) => (b.k === "ecom" ? `data-avecomband="${i == null ? -1 : i}"` : `data-avgrp="type" data-avkey="${b.k}" data-avtypekey="${b.k}"${i == null ? "" : ` data-avband="${i}"`}${kvi}`);
    NCSV.avtype = () => ["availability_criteria", ["Availability criteria", "Avg %", ...AV_BANDS], blocks.map((b) => [b.title, isNum(b.avg) ? (b.avg * 100).toFixed(2) : "", ...b.bands]), S.av.generatedAt.slice(0, 10)];
    const name = { core: "Core", promo: "Promo", kvi: "KVI", all: "Over all", ecom: "E-Commerce" };
    const sub = (b) => (b.k === "ecom" ? `${int(scans.ecom.byS.size)} SKUs · ${int(scans.ecom.byO.size)} outlets` : `${int(scans[b.k].skus.length)} SKUs${b.k === "all" ? " (unique)" : ""} · ${int(scans[b.k].outs.length)} outlets${kviOnly ? " (KVI outlets)" : ""}`);
    const single = kinds.length === 1;
    const pairs = (b) => (!single ? null : b.k === "ecom" ? scans.ecom.tot : scans[b.k].tot);
    const cards = blocks.map((b) => avCriteriaCard({ name: single ? `${name[b.k]} availability` : name[b.k], sub: sub(b) + (single && b.k === "ecom" ? ` · YES assortment only, ${int(S.av.ecom.assortmentNo)} NO pairs not counted` : ""),
      avg: b.avg, bands: b.bands, head: attr(b), band: (i) => attr(b, i), pairs: pairs(b), pairsLabel: b.k === "ecom" ? "YES items" : null }, single)).join("");
    return `<section class="panel"><div class="panel-head"><div><h2>${single ? "Availability" : "Availability criteria"}</h2><p>${single ? "Share of items available, the average of outlet availability, and how many outlets fall in each band." : "Average of outlet availability for each type, and how many outlets fall in each band."} Click ${single ? "the title" : "a card"} or a band for its outlets and items.</p></div><div class="panel-tools">${csvBtn("avtype")}</div></div>
      <div class="panel-body"><div class="av-cards${kinds.length === 1 ? " single" : ""}">${cards}</div></div></section>`;
  }
  function openAvEcomBand(band) {
    const d = S.av, e = avEcomScan();
    const rows = [...e.byO].map(([oi, a]) => ({ o: d.outlets[oi], a })).filter((r) => band < 0 || avBandIdx(avRate(r.a)) === band).sort((p, q) => avRate(p.a) - avRate(q.a));
    const tot = avAcc();
    rows.forEach(({ a }) => { tot.slots += a.slots; tot.ok += a.ok; a.st.forEach((v, i) => (tot.st[i] += v)); });
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = band < 0 ? "E-Commerce outlets" : `E-Commerce outlets at ${AV_BANDS[band]}`;
    $("#drawerBody").innerHTML = `<div class="stat-grid three"><div class="stat"><small>Availability</small><strong>${avPct(tot)}</strong><div style="font-size:12px">${int(tot.ok)} of ${int(tot.slots)} YES items</div></div>
        <div class="stat"><small>Outlets</small><strong>${int(rows.length)}</strong></div><div class="stat"><small>Out of stock</small><strong class="down">${int(tot.st[2])}</strong></div></div>
      <div><div class="section-title">Outlets, lowest availability first</div><div class="table-wrap" style="max-height:520px"><table class="compact"><thead><tr><th>Outlet</th><th class="num">Availability</th><th class="num">Available</th><th class="num">Out of stock</th></tr></thead><tbody>
        ${rows.map(({ o, a }) => `<tr data-avecom="${esc(o.c)}" tabindex="0" style="cursor:pointer"><td><span class="cell-primary">${esc(o.c)} · ${esc(o.n)}</span><span class="cell-secondary">${esc(avUnassigned(o.dim.zn))} · ${esc(avUnassigned(o.dim.rl))}</span></td><td class="num"><strong>${avPct(a)}</strong></td><td class="num">${int(a.ok)} / ${int(a.slots)}</td><td class="num">${int(a.st[2])}</td></tr>`).join("")}</tbody></table></div></div>`;
    wireAv($("#drawerBody"));
    showDrawer();
  }

  // ---- pages
  function pageAVS() {
    const g = avGuard(); if (g) return g;
    const all = avScan("all"), c = avScan("core"), p = avScan("promo"), k = avScan("kvi"), e = avEcomScan();
    const r = avRate(all.tot), b = avBand(r), fill = Math.min(1, r || 0) * 100;
    return `${avBar()}
      <section class="panel"><div class="panel-body"><div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
        ${kpi({ hero: true, label: `Core, Promo and KVI availability at ${avDays()} day${avDays() === 1 ? "" : "s"} of cover`, value: avPct(all.tot), accent: "var(--series-2)",
          sub: `${chip(b)}<span>${int(all.tot.ok)} of ${int(all.tot.slots)} outlet × SKU pairs</span>`,
          foot: `<div class="bar" style="flex:1 1 100%;margin:2px 0 6px" role="img" aria-label="Availability ${avPct(all.tot)}"><i style="width:${fill}%;background:var(--${b.cls})"></i></div><span>${int(all.outs.length)} outlets · ${int(all.skus.length)} SKUs</span><span>Shortfall ${int(all.tot.short)} units</span>` })}
        ${avCard("Core", c.tot, "var(--series-2)")}${avCard("Promo", p.tot, "var(--series-3)")}${avCard("KVI", k.tot, "var(--series-1)")}
        ${avCard("E-Commerce", e.tot, "var(--series-4)", `<span>${int(e.byO.size)} outlets · YES assortment only</span>`)}
      </div></div></section>
      ${avTypeCriteria(["core", "promo", "kvi", "all", "ecom"], { core: c, promo: p, kvi: k, all, ecom: e })}
      ${avRhoMatrix({ core: c, promo: p, kvi: k, all })}
      ${avCriteria(all)}
      <div class="grid-h">${avOutletTable("av-sum-o", all, "Lowest outlets", "all", 10)}${avSkuTable("av-sum-s", all, "Lowest SKUs", "all", 10)}</div>`;
  }
  function pageAVType(type) {
    const g = avGuard(); if (g) return g;
    const kviOnly = type === "kvi" && S.avv.kviOnly === "yes";
    const scan = avScan(type, kviOnly), name = AV_TYPES.find((t) => t[0] === type)[1];
    const extra = type === "kvi" ? avSeg("kviOnly", [["no", "All outlets"], ["yes", "KVI outlets only"]], "Outlets") : "";
    return `${avBar(extra)}
      ${avTypeCriteria([type], { [type]: scan }, kviOnly)}
      ${avGroupTable(`av-${type}-zn`, scan, S.avv.glevel, type, avSeg("glevel", [["zn", "Zonal"], ["rl", "RHO"]], "Group by"))}
      ${avOutletTable(`av-${type}-o`, scan, `${name} availability by outlet`, type)}`;
  }
  function pageAVK() {
    const g = avGuard(); if (g) return g;
    const type = S.avv.type, scan = avScan(type);
    return `${avBar()}${avSkuTable("av-sku", scan, "SKU wise availability", type, 50, avSeg("type", AV_TYPES, "SKU type"))}`;
  }
  function pageAVB() {
    const g = avGuard(); if (g) return g;
    const type = S.avv.type, scan = avScan(type);
    const tools = `${avSeg("level", Object.entries(AV_LEVELS), "Level")}${avSeg("type", AV_TYPES, "SKU type")}`;
    return `${avBar()}<section class="panel"><div class="panel-head"><div><h2>View by</h2><p>Switch between product division, CAT3, zonal, regional leader and outlet. Click a row to go one level down.</p></div><div class="panel-tools">${tools}</div></div></section>
      ${avGroupTable("av-b", scan, S.avv.level, type)}`;
  }
  function pageAVE() {
    const g = avGuard(); if (g) return g;
    const d = S.av, e = avEcomScan(), t = e.tot;
    const stamp = d.generatedAt.slice(0, 10), lv = S.avv.elevel, id = "av-e-o", gd = gdrill(id, lv);
    const tools = gd ? "" : avSeg("elevel", [["outlet", "Outlet"], ["zn", "Zonal"], ["rl", "RHO"]], "Group by");
    const outletRows = (keep) => [...e.byO].filter(([oi]) => keep(d.outlets[oi])).map(([oi, a]) => { const o = d.outlets[oi]; return { ...a, code: o.c, name: o.n, sub: `${avUnassigned(o.dim.zn)} · ${avUnassigned(o.dim.rl)}` }; });
    let table;
    if (lv === "outlet" || gd) {
      table = mountTable(id, { title: gd ? `E-Commerce outlets of ${avUnassigned(gd.key)}` : "E-Commerce availability by outlet", file: gd ? `availability_ecom_outlets_${gd.key}` : "availability_ecom_outlets", stamp, banner: gBanner(id, gd), tools,
        desc: (n) => `${int(n)} outlets, lowest availability first. Click an outlet for its missing items.`,
        rows: outletRows((o) => !gd || o.dim[lv] === gd.key), key: (x) => x.code, searchText: (x) => `${x.code} ${x.name} ${x.sub}`, defaultSort: "rate", defaultDir: "asc",
        rowAttr: (x) => `data-avecom="${esc(x.code)}" tabindex="0"`, cols: avCols(avOutletFirst) });
    } else {
      const g = new Map();
      e.byO.forEach((a, oi) => {
        const k = d.outlets[oi].dim[lv], x = g.get(k) || { ...avAcc(), key: k, name: k, n: 0 };
        x.slots += a.slots; x.ok += a.ok; a.st.forEach((v, i) => (x.st[i] += v)); x.stock += a.stock; x.perDay += a.perDay; x.short += a.short; x.n++;
        g.set(k, x);
      });
      table = mountTable(id, { title: `E-Commerce availability by ${lv === "zn" ? "zonal" : "RHO"}`, file: `availability_ecom_${lv}`, stamp, tools,
        desc: (n) => `${int(n)} groups, lowest availability first. Group figures are sums of their YES items. Click a group to list its outlets.`,
        rows: [...g.values()], key: (x) => x.key, searchText: (x) => x.name, defaultSort: "rate", defaultDir: "asc",
        rowAttr: (x) => `data-gpick="${id}" data-glevel="${lv}" data-gkey="${esc(x.key)}" tabindex="0" title="List ${esc(avUnassigned(x.name))}'s E-Commerce outlets"`,
        cols: avCols({ k: "name", label: lv === "zn" ? "Zonal" : "RHO", val: (x) => x.name, fmt: (x) => `<span class="cell-primary">${esc(avUnassigned(x.name))}</span>`, csv: (x) => avUnassigned(x.name) }, "Outlets") });
    }
    return `${avBar("", true)}
      ${avTypeCriteria(["ecom"], { ecom: e })}
      ${table}`;
  }

  // ---- drawers
  function avPairTable(rows, first) {
    if (!rows.length) return '<p class="net-empty">Nothing missing here.</p>';
    return `<div class="table-wrap" style="max-height:none"><table class="compact"><thead><tr><th>${first}</th><th>Status</th><th class="num">Stock</th><th class="num">Per day</th><th class="num">Needed</th></tr></thead><tbody>
      ${rows.slice(0, 150).map((x) => `<tr><td><span class="cell-primary">${esc(x.name)}</span><span class="cell-secondary">${esc(x.sub)}</span></td><td>${chip(AV_ST[x.k])}</td><td class="num">${int(x.st)}</td><td class="num">${x.pd ? x.pd.toFixed(1) : "—"}</td><td class="num">${x.need ? int(x.need) : "—"}</td></tr>`).join("")}
      </tbody></table></div>${rows.length > 150 ? `<p class="muted" style="margin:0;font-size:12px">Showing 150 of ${int(rows.length)}; the table CSV on the page has all of them.</p>` : ""}`;
  }
  function openAvOutlet(code, type) {
    const d = S.av, o = d.byCode.get(code);
    if (!o) return;
    S.lastFocus = document.activeElement;
    const days = avDays(), base = o.i * d.S, per = {};
    ["core", "promo", "kvi"].forEach((t) => (per[t] = avAcc()));
    const miss = [];
    for (const s of avSkus(type)) {
      const st = d.stock[base + s.i], sl = d.sales60[base + s.i], k = avStatus(st, sl, days);
      ["core", "promo", "kvi"].forEach((t) => { if (s[t]) avAdd(per[t], st, sl, days, k); });
      if (!AV_OK[k]) miss.push({ k, st, pd: sl > 0 ? sl / 60 : 0, need: sl > 0 ? Math.max(0, (sl / 60) * days - st) : 0, name: s.n, sub: `${s.c} · ${s.cat3 || "—"} · ${avTypeChips(s)}` });
    }
    miss.sort((a, b) => b.need - a.need || a.k - b.k);
    $("#drawerTitle").textContent = `${o.c} · ${o.n}`;
    $("#drawerBody").innerHTML = `<p class="muted" style="margin:0">${esc([o.dim.zn, o.dim.rl, o.dim.fmt, o.kvi ? "KVI outlet" : "", o.ecom ? "E-Commerce outlet" : ""].filter((x) => x && x !== NET_MISS).join(" · "))}</p>
      <div class="stat-grid three">${["core", "promo", "kvi"].map((t) => `<div class="stat"><small>${t.toUpperCase()}</small><strong>${avPct(per[t])}</strong><div style="font-size:12px">${int(per[t].ok)} of ${int(per[t].slots)} available</div></div>`).join("")}</div>
      <div><div class="section-title">Missing or short at ${days} day${days === 1 ? "" : "s"} of cover (${int(miss.length)} items${S.avv.nd || S.avv.cat3 ? ", within the division and CAT3 picked" : ""})</div>${avPairTable(miss, "SKU")}</div>`;
    showDrawer();
  }
  function openAvSku(code, type) {
    const d = S.av, s = d.skuByCode.get(code);
    if (!s) return;
    S.lastFocus = document.activeElement;
    const days = avDays(), kviOnly = type === "kvi" && S.avv.kviOnly === "yes", a = avAcc(), miss = [];
    for (const o of avOutlets(kviOnly)) {
      const i = o.i * d.S + s.i, st = d.stock[i], sl = d.sales60[i], k = avStatus(st, sl, days);
      avAdd(a, st, sl, days, k);
      if (!AV_OK[k]) miss.push({ k, st, pd: sl > 0 ? sl / 60 : 0, need: sl > 0 ? Math.max(0, (sl / 60) * days - st) : 0, name: `${o.c} · ${o.n}`, sub: `${o.dim.zn} · ${o.dim.rl}` });
    }
    miss.sort((x, y) => y.need - x.need || x.k - y.k);
    $("#drawerTitle").textContent = `${s.c} · ${s.n}`;
    $("#drawerBody").innerHTML = `<p class="muted" style="margin:0">${esc([s.nd, s.cat3, avTypeChips(s)].filter(Boolean).join(" · "))}</p>
      <div class="stat-grid three"><div class="stat"><small>Availability</small><strong>${avPct(a)}</strong><div style="font-size:12px">${int(a.ok)} of ${int(a.slots)} outlets</div></div>
        <div class="stat"><small>Out of stock</small><strong class="down">${int(a.st[2])}</strong><div style="font-size:12px">outlets</div></div>
        <div class="stat"><small>Sales per day</small><strong>${int(a.perDay)}</strong><div style="font-size:12px">across these outlets</div></div></div>
      <div><div class="section-title">Outlets missing it or short at ${days} day${days === 1 ? "" : "s"} of cover</div>${avPairTable(miss, "Outlet")}</div>`;
    showDrawer();
  }
  function openAvEcom(code) {
    const d = S.av, o = d.byCode.get(code);
    if (!o) return;
    S.lastFocus = document.activeElement;
    const f = S.avv, miss = [], a = avAcc();
    for (const [oi, si, st, d2, mon] of d.ecom.pairs) {
      if (oi !== o.i) continue;
      const s = d.ecom.skus[si];
      if ((f.nd && s.nd !== f.nd) || (f.cat3 && s.cat3 !== f.cat3)) continue;
      const k = avEcomStatus(st, d2);
      a.slots++; a.st[k]++; if (AV_OK[k]) a.ok++;
      if (!AV_OK[k]) miss.push({ k, st, pd: (mon || 0) / 30, need: Math.max(0, d2 - st), name: s.n, sub: `${s.c} · ${s.cat3 || "—"}` });
    }
    miss.sort((x, y) => y.need - x.need);
    $("#drawerTitle").textContent = `${o.c} · ${o.n} (E-Commerce)`;
    $("#drawerBody").innerHTML = `<div class="stat-grid three"><div class="stat"><small>E-Commerce availability</small><strong>${avPct(a)}</strong><div style="font-size:12px">${int(a.ok)} of ${int(a.slots)} YES items</div></div>
      <div class="stat"><small>Out of stock</small><strong class="down">${int(a.st[2])}</strong></div><div class="stat"><small>Below DOS 2 Days</small><strong>${int(a.st[1])}</strong></div></div>
      <div><div class="section-title">Missing or below DOS 2 Days</div>${avPairTable(miss, "SKU")}</div>`;
    showDrawer();
  }

  // ---- data quality (shown on the Data quality page)
  function avQualityPanel() {
    const head = `<div class="panel-head"><div><h2>Availability files</h2><p>From the mother Drive folder, recognised by their columns: SKU lists, stock, 60-day sales (DOS), E-Commerce assortment, KVI outlets and Zone Distribution. Stock and DOS should be updated daily.</p></div></div>`;
    if (!S.av) { loadAv(); return `<section class="panel">${head}<div class="panel-body"><p class="muted" style="margin:0">${S.avErr ? `av.json could not be loaded (${esc(S.avErr)}).` : "Loading…"}</p></div></section>`; }
    const d = S.av, q = d.quality, kinds = { lists: "SKU lists (Core, Promo, KVI, ECOM)", stock: "Stock", dos: "Sales, 60 days (DOS)", ecom: "E-Commerce assortment and DOS 2 Days", kviOutlets: "KVI outlets", zones: "Zone Distribution" };
    const item = (lvl, title, body) => `<div class="issue"><span>${chip({ cls: lvl, label: lvl === "good" ? "Passed" : lvl === "warn" ? "Warning" : "Note" })}</span><div>${esc(title)}<small>${body}</small></div></div>`;
    return `<section class="panel">${head}<div class="table-wrap"><table><thead><tr><th>File</th><th>Used as</th><th>Updated in Drive</th></tr></thead><tbody>
      ${d.files.map((f) => `<tr><td class="cell-primary">${esc(f.name)}</td><td>${esc(kinds[f.kind] || f.kind)}</td><td>${f.modified ? fdate(f.modified.slice(0, 10)) : "—"}</td></tr>`).join("")}</tbody></table></div>
      <div class="panel-body">
        ${item(d.stale.length ? "warn" : "good", d.stale.length ? "Stock or sales file is more than 2 days old" : "Stock and sales files are current", d.stale.length ? esc(d.stale.map((x) => x.name).join(", ")) : "Both were updated in the last 2 days.")}
        ${item(d.excluded.length ? "info" : "good", `${int(d.excluded.length)} outlets left out everywhere`, d.excluded.length ? esc(d.excluded.map((x) => `${x.c}${x.n ? " " + x.n : ""} (${x.reason.toLowerCase()})`).join("; ")) : "Every outlet has Core, KVI or Promo stock and sales.")}
        ${item(q.unmappedOutlets.length ? "warn" : "good", q.unmappedOutlets.length ? "Counted outlets missing from Zone Distribution" : "All counted outlets are in Zone Distribution", q.unmappedOutlets.length ? `${esc(q.unmappedOutlets.join(", "))}. They show as "${NET_MISS}".` : "Every counted outlet joined to the outlet master.")}
        ${item(q.skusNotInStock.length || q.skusNotInDos.length ? "warn" : "good", "SKU coverage", `${int(q.skusNotInStock.length)} listed SKUs are missing from the stock file${q.skusNotInStock.length ? ` (${esc(q.skusNotInStock.slice(0, 30).join(", "))})` : ""}; ${int(q.skusNotInDos.length)} have no sales in the DOS file.`)}
        ${item("info", "KVI outlets", `${int(q.kviOutletsListed)} listed, ${int(q.kviOutletsCounted)} counted. Used only for the "KVI outlets only" switch on the KVI page.`)}
        ${item(q.ecomListedNotInFile.length ? "warn" : "good", "E-Commerce SKUs", `${int(d.ecom.skus.length)} SKUs at ${int(new Set(d.ecom.pairs.map((p) => p[0])).size)} outlets; ${int(d.ecom.assortmentNo)} Assortment = NO pairs are not counted.${q.ecomListedNotInFile.length ? ` ${int(q.ecomListedNotInFile.length)} ECOM-list SKUs are not in the E-Commerce DOS file.` : ""}`)}
      </div></section>`;
  }

  function wireAv(root) {
    $$("[data-avsel]", root).forEach((s) => (s.onchange = () => { S.avv[s.dataset.avsel] = s.value; if (s.dataset.avsel === "nd") S.avv.cat3 = ""; changed(); }));
    $$("[data-avset]", root).forEach((b) => (b.onclick = () => { S.avv[b.dataset.avset] = b.dataset.val; changed(); }));
    const on = (sel, fn) => $$(sel, root).forEach((n) => { n.onclick = () => fn(n); n.onkeydown = (e) => { if (e.key === "Enter") fn(n); }; });
    on("[data-avoutlet]", (n) => openAvOutlet(n.dataset.avoutlet, n.dataset.avtype || "all"));
    on("[data-avsku]", (n) => openAvSku(n.dataset.avsku, n.dataset.avtype || "all"));
    on("[data-avecom]", (n) => openAvEcom(n.dataset.avecom));
    on("[data-avgrp]", (n) => openAvGroup(n.dataset.avgrp, n.dataset.avkey, n.dataset.avband != null ? Number(n.dataset.avband) : null, n.dataset.avtypekey || "all", n.dataset.avkvi === "yes"));
    on("[data-avecomband]", (n) => openAvEcomBand(Number(n.dataset.avecomband)));
  }

  // ------------------------------------------------------------------ drawer
  function openOutlet(code) {
    const o = rep()?.outlets.find((x) => x.c === code);
    if (!o) return;
    const m = o.m || {}, a = agg([o]);
    S.lastFocus = document.activeElement;
    $("#drawerTitle").textContent = `${o.c} ${o.nm}`;
    const stat = (l, v, s = "") => `<div class="stat"><small>${l}</small><strong>${v}</strong>${s ? `<div style="font-size:12px">${s}</div>` : ""}</div>`;
    const fact = (l, v) => (v ? `<dt>${l}</dt><dd>${v}</dd>` : "");
    $("#drawerBody").innerHTML = `
      <div class="stat-grid">
        ${stat("Achievement", pct(a.ach), a.t > 0 ? `${chip(band(a.ach))} ${bdt(a.a)} of ${bdt(a.t)}` : `No target · achieved ${bdt(a.aAll)}`)}
        ${stat("Sales", bdt(a.s), `${delta(a.gy)} vs last year`)}
        ${stat("Sales vs last month", delta(a.gm), `last month ${bdt(a.sm)}`)}
        ${stat("Footfall", int(a.f), `${delta(growth(a.f, a.fy))} vs last year`)}
        ${stat("Average bill value", bdt(a.bk), `${delta(growth(a.bk, a.bky))} vs last year`)}
        ${stat("Gross profit margin", pct(a.gp), `${delta(isNum(a.gp) && isNum(a.gpy) ? a.gp - a.gpy : null, "pp")} vs last year`)}
      </div>
      ${o.m ? "" : '<p class="note">This outlet is not in the latest outlet master (zone distribution), so its region, format and ownership are unknown. Outlets with no sales this period are usually closed.</p>'}
      <dl class="facts">
        ${fact("Regional leader", esc(o.dim.rl))}${fact("Zonal", esc(o.dim.zn) + (m.zc ? ` <a href="tel:${esc(m.zc)}">${esc(m.zc)}</a>` : ""))}
        ${fact("Outlet in-charge", esc(o.oi))}${fact("Format", esc(m.fmt))}${fact("Size", m.sft ? int(m.sft) + " sq ft" : "")}
        ${fact("Opened", m.ld ? fdate(m.ld) : "")}${fact("Ownership", esc(m.own))}${fact("PNP status", esc(m.pnp))}
        ${fact("Area", esc([m.area, m.dis, m.div].filter(Boolean).join(", ")))}${fact("Location type", esc(m.loc))}
        ${fact("Same store", o.ssy ? "Yes, vs last year" : "No")}${fact("Map", m.geo ? `<a href="${esc(m.geo)}" target="_blank" rel="noopener">Open in maps</a>` : "")}
      </dl>`;
    showDrawer();
  }
  function showDrawer() {
    $("#drawer").hidden = false; $("#scrim").hidden = false; document.body.style.overflow = "hidden";
    $("#drawerClose").focus();
  }
  function closeDrawer() {
    if ($("#drawer").hidden) return;
    $("#drawer").hidden = true; document.body.style.overflow = ""; S.ageDrill = null;
    if (!$("#rail").classList.contains("open")) $("#scrim").hidden = true;
    S.lastFocus?.focus?.();
  }
  const closeRail = () => { $("#rail").classList.remove("open"); if ($("#drawer").hidden) $("#scrim").hidden = true; };

  // ------------------------------------------------------------------ render
  function render() {
    renderNav(); renderTop(); renderPills();
    $("#filters").hidden = !FILTER_PAGES.has(S.page);
    if (FILTER_PAGES.has(S.page)) renderFilters();
    const p = S.page;
    const PAGE = { overview: pageOverview, achievement: pageAchievement, growth: pageGrowth, footfall: pageFootfall, ranking: pageRanking, category: pageCategory, loss: pageLoss, performance: pageKPI, dq: pageDQ, on: pageON, gm: pageGM, cw: pageCW, cwl: pageCWL, cwx: pageCWX, cwb: pageCWB, cwm: pageCWM, cwo: pageCWO,
      avs: pageAVS, avk: pageAVK, avc: () => pageAVType("core"), avp: () => pageAVType("promo"), avv: () => pageAVType("kvi"), ave: pageAVE, avb: pageAVB };
    AFTER = [];
    const html = PAGE[p] ? PAGE[p]() : EMBEDS[p] ? pageEmbed(p) : pageOverview();
    // keep embedded iframes alive when only filters change
    const view = $("#view");
    if (!(EMBEDS[p] && view.dataset.page === p)) view.innerHTML = html;
    view.dataset.page = p;
    Object.keys(S.tables).forEach((id) => $("#t-" + id) && drawTable(id));
    wireDyn(view);
    AFTER.forEach((f) => f());
    const tb = $(".topbar"); if (tb) document.documentElement.style.setProperty("--k-top", tb.offsetHeight + "px");
  }

  function route() {
    const h = location.hash.slice(1);
    S.page = TITLES[h] ? h : "overview";
    const grp = NAV.find((g) => g.items.some(([k]) => k === S.page))?.group;
    if (grp && UI.navOpen?.[grp] === false) { UI.navOpen = { ...UI.navOpen }; delete UI.navOpen[grp]; saveUI(); }
    render();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------------ boot
  $("#themeBtn").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("opsdash-theme", t); } catch (e) {}
    if (NET_PAGES.has(S.page)) render(); // charts resolve colour tokens when drawn
  });
  $("#resetBtn").addEventListener("click", () => { DIMS.concat(NET_DIMS).forEach(([k]) => S.filters[k].clear()); S.bands.clear(); S.on.drill = null; S.lossPick = null; S.gdrill = {}; S.ov = { ...S.ov, rl: null, zn: null }; S.lv = { ...S.lv, rl: null, zn: null }; S.cwh = { ...S.cwh, rl: null, zn: null }; changed(); });
  applyRail();
  $("#railBtn").addEventListener("click", () => { UI.railHidden = !UI.railHidden; saveUI(); applyRail(); });
  $("#menuBtn").addEventListener("click", () => { $("#rail").classList.add("open"); $("#scrim").hidden = false; });
  $("#scrim").addEventListener("click", () => { closeDrawer(); closeRail(); });
  $("#drawerClose").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !closeReport()) { closeDrawer(); closeRail(); } });
  $("#reportClose").addEventListener("click", closeReport);
  $("#reportPrint").addEventListener("click", () => window.print());
  $("#reportPng").addEventListener("click", reportPng);
  // The growth & momentum charts are drawn at their measured width, so redraw when that really changes.
  new ResizeObserver(() => {
    const svg = $("#quadrantChart");
    if (S.page !== "gm" || !svg || Math.abs(svg.parentElement.clientWidth - gmChartWidth) < 12) return;
    render();
  }).observe($("#view"));
  document.addEventListener("click", (e) => { if (S.openDim && !e.target.closest(".ms")) { S.openDim = null; renderFilters(); } }, true);
  window.addEventListener("hashchange", route);

  (window.__DATA__ ? Promise.resolve(window.__DATA__) : fetch("data/data.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }))
    .then((d) => {
      prep(d);
      S.data = d;
      if (!d.tilldate && d.monthend) S.period = "monthend";
      route();
    })
    .catch((e) => {
      $("#view").innerHTML = `<p class="empty">The data file could not be loaded (${esc(e.message)}). Run the "Refresh data" workflow on GitHub, then reload this page.</p>`;
    });
})();
