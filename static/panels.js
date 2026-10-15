// Màn hình thêm sau bản gốc: tab, tổng quan, cảnh báo, chi tiết kênh, so sánh, chế độ xem,
// nhập file, bảng lệnh, trợ giúp phím tắt. Dùng chung `table`, `load`, `refresh`… của main.js.

const rowsNow = () => window.channelRows || [];
const rowOf = (u) => rowsNow().find((c) => c.username === u);
const displayName = (c) => "@" + (c.unique_id || c.username);
const plainNf = (n) => Charts.full(n);
const typing = (e) => !!e.target.closest?.("input, textarea, select, [contenteditable]");
const dialogOpen = () => !!document.querySelector("dialog[open]");

// ---------------------------------------------------------------- tab

const TABS = ["channels", "overview", "alerts"];
let currentTab = "channels";

function showTab(name) {
  if (!TABS.includes(name)) name = "channels";
  currentTab = name;
  for (const t of TABS) {
    $(`#pane-${t}`).classList.toggle("on", t === name);
    const btn = document.querySelector(`.tab[data-tab="${t}"]`);
    btn.setAttribute("aria-selected", String(t === name));
  }
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  if (name === "overview") renderOverview();
  if (name === "alerts") renderAlerts();
}
document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------- tổng quan

const ovState = { win: "d7", metric: "followers" };
let ovTimer = null;
const stopCharts = [];

function seg(options, value, attr) {
  return `<div class="seg">${options.map(([v, l]) => `<button data-${attr}="${v}" class="${String(v) === String(value) ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`;
}

function chLink(c) {
  return `<a href="#" data-open="${esc(c.username)}">${esc(displayName(c))}</a>`;
}

async function renderOverview() {
  clearTimeout(ovTimer);
  const pane = $("#pane-overview");
  let o;
  try {
    o = await api("/api/overview");
  } catch (e) {
    pane.innerHTML = `<div class="none-yet">Không tải được tổng quan: ${esc(e.message)}</div>`;
    return;
  }
  if (currentTab !== "overview") return;
  stopCharts.splice(0).forEach((f) => f());
  const t = o.totals;
  const card = (k, v, s = "", cls = "") => `<div class="card ${cls}"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  const list = o.gainers[ovState.win][ovState.metric];
  const unit = ovState.metric === "followers" ? "follow" : "view";
  const gainRows = list.length
    ? `<table class="mini"><tr><th>#</th><th>Kênh</th><th class="r">${ovState.metric === "followers" ? "Follow" : "Tổng view"} +/−</th><th></th></tr>` +
      list.map((r, i) => `<tr><td class="muted">${i + 1}</td><td>${chLink(r)}</td><td class="r">${r.delta > 0 ? "+" : r.delta < 0 ? "−" : ""}${plainNf(Math.abs(r.delta))}</td><td class="muted">${r.partial ? "mới theo dõi" : ""}</td></tr>`).join("") +
      "</table>"
    : `<div class="none-yet">Chưa đủ lịch sử: cần ít nhất hai lần cập nhật cách nhau để tính mức tăng ${unit}.</div>`;
  const miniList = (rows, empty, extra) =>
    rows.length
      ? '<table class="mini">' + rows.map((c) => `<tr><td>${chLink(c)}</td><td class="muted clip" title="${esc(extra(c))}">${esc(extra(c))}</td></tr>`).join("") + "</table>"
      : `<div class="none-yet">${empty}</div>`;
  const videos = o.top_videos.length
    ? '<table class="mini"><tr><th>Video</th><th>Kênh</th><th class="r">View</th><th class="r">Tim</th><th>Đăng</th></tr>' +
      o.top_videos.map((v) => `<tr><td class="clip"><a href="https://www.tiktok.com/@${esc(v.username)}/video/${esc(v.id)}" target="_blank">${esc((v.description || "(không có mô tả)").slice(0, 70))}</a></td><td>${chLink({ username: v.username, unique_id: (rowOf(v.username) || {}).unique_id })}</td><td class="r">${plainNf(v.play)}</td><td class="r">${plainNf(v.digg)}</td><td class="muted">${fmtAgo(v.create_time)}</td></tr>`).join("") +
      "</table>"
    : '<div class="none-yet">Chưa có video đăng trong 30 ngày qua trong dữ liệu đã quét.</div>';

  pane.innerHTML =
    `<div class="cards">` +
    card("Kênh", plainNf(t.channels), t.working ? `${t.working} đang chờ/quét` : "") +
    card("Follow", plainNf(t.followers)) +
    card("Lượt thích", plainNf(t.likes)) +
    card("Tổng view (đã quét)", plainNf(t.total_views), `${plainNf(t.videos)} video`) +
    card("Video 7 ngày qua", plainNf(t.posts_7d)) +
    (t.errors ? card("Kênh lỗi", plainNf(t.errors), "", "warn") : "") +
    (t.interrupted ? card("Bị dừng giữa chừng", plainNf(t.interrupted), "", "warn") : "") +
    (t.stale ? card("Lâu chưa cập nhật", plainNf(t.stale), "quá 3 ngày") : "") +
    `</div>` +
    `<div class="grid2">` +
    `<div class="panel"><h4>Tổng follow theo thời gian</h4><div id="ovFollowers"></div></div>` +
    `<div class="panel"><h4>Tổng view theo thời gian</h4><div id="ovViews"></div></div>` +
    `</div>` +
    `<div class="panel"><h4>Tăng nhanh nhất <span class="spacer"></span>` +
    seg([["d1", "24 giờ"], ["d7", "7 ngày"], ["d30", "30 ngày"]], ovState.win, "win") + " " +
    seg([["followers", "Follow"], ["views", "View"]], ovState.metric, "metric") +
    `</h4>${gainRows}</div>` +
    `<div class="grid2">` +
    `<div class="panel"><h4>Lâu chưa cập nhật <span class="spacer"></span>${o.stale.length ? '<button class="btn" id="ovUpdateStale">↻ Cập nhật</button>' : ""}</h4>${miniList(o.stale, "Mọi kênh đều mới cập nhật.", (c) => (c.updated_at ? "cập nhật " + new Date(c.updated_at * 1000).toLocaleDateString("vi-VN") : "chưa từng cập nhật"))}</div>` +
    `<div class="panel"><h4>Đang lỗi</h4>${miniList(o.errors, "Không có kênh nào đang lỗi.", (c) => c.message || "Lỗi")}</div>` +
    `</div>` +
    `<div class="panel"><h4>Video nổi bật 30 ngày qua</h4>${videos}</div>`;

  const series = (key) => [{ name: "", points: o.series.map((p) => [p.ts, p[key]]) }];
  stopCharts.push(Charts.line($("#ovFollowers"), series("followers"), { fmt: plainNf, label: "Tổng follow" }));
  stopCharts.push(Charts.line($("#ovViews"), series("total_views"), { fmt: plainNf, label: "Tổng view" }));
  $("#ovUpdateStale")?.addEventListener("click", () => {
    refresh(o.stale.map((c) => ({ username: c.username })), { mode: "quick" });
  });
  if (currentTab === "overview") ovTimer = setTimeout(renderOverview, 30000);
}

$("#pane-overview").addEventListener("click", (e) => {
  const open = e.target.closest("[data-open]");
  if (open) {
    e.preventDefault();
    openDrawer(open.dataset.open);
    return;
  }
  const w = e.target.closest("[data-win]");
  if (w) { ovState.win = w.dataset.win; renderOverview(); return; }
  const m = e.target.closest("[data-metric]");
  if (m) { ovState.metric = m.dataset.metric; renderOverview(); }
});

// ---------------------------------------------------------------- cảnh báo

let alertState = { unread: 0, seen: null };

async function pollAlerts(render = false) {
  try {
    const a = await api("/api/alerts?limit=100");
    const badge = $("#alertCount");
    badge.hidden = !a.unread;
    badge.textContent = a.unread > 99 ? "99+" : a.unread;
    if (alertState.seen !== null && a.unread > alertState.unread) {
      const n = a.unread - alertState.unread;
      toast(`${n} cảnh báo mới`, "", { ms: 6000, action: { label: "Xem", fn: () => showTab("alerts") } });
    }
    alertState = { unread: a.unread, seen: true };
    if (render || currentTab === "alerts") paintAlerts(a);
  } catch {}
}

function paintAlerts(a) {
  const pane = $("#pane-alerts");
  const icon = { followers: "⇅", new_video: "▶" };
  pane.innerHTML =
    `<div class="panel"><h4>Cảnh báo <span class="spacer"></span>` +
    `<button class="btn" id="alertsRead" ${a.unread ? "" : "disabled"}>✓ Đánh dấu đã đọc tất cả</button></h4>` +
    (a.alerts.length
      ? `<div class="alert-list">${a.alerts.map((x) => `<div class="alert-item ${x.read ? "" : "unread"}"><span class="alert-ico">${icon[x.kind] || "•"}</span><span><a href="#" data-open="${esc(x.username)}">${esc(x.text)}</a></span><span class="t">${fmtAgo(x.ts)}</span></div>`).join("")}</div>`
      : '<div class="none-yet">Chưa có cảnh báo. Cảnh báo xuất hiện khi follow đổi mạnh hoặc kênh đăng video mới giữa hai lần cập nhật; ngưỡng chỉnh trong Cài đặt.</div>') +
    `</div>`;
}

async function renderAlerts() {
  await pollAlerts(true);
}

$("#pane-alerts").addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open]");
  if (open) {
    e.preventDefault();
    openDrawer(open.dataset.open);
  } else if (e.target.closest("#alertsRead")) {
    await api("/api/alerts/read", {});
    await pollAlerts(true);
  }
});

// ---------------------------------------------------------------- chi tiết kênh (drawer)

const dr = { username: null, days: 30, metric: "followers", stop: null };
const METRIC_LABEL = { followers: "Follow", likes: "Lượt thích", total_views: "Tổng view", video_count: "Số video" };

function openDrawer(target) {
  const username = typeof target === "string" ? target : target?.username;
  if (!username) return;
  dr.username = username;
  $("#drawerShade").hidden = false;
  requestAnimationFrame(() => {
    $("#drawerShade").classList.add("on");
    $("#drawer").classList.add("on");
  });
  $("#drawer").setAttribute("aria-hidden", "false");
  paintDrawer();
}

function closeDrawer() {
  dr.stop?.();
  dr.stop = null;
  dr.username = null;
  $("#drawer").classList.remove("on");
  $("#drawerShade").classList.remove("on");
  $("#drawer").setAttribute("aria-hidden", "true");
  setTimeout(() => !dr.username && ($("#drawerShade").hidden = true), 220);
}
$("#drawerShade").addEventListener("click", closeDrawer);

async function paintDrawer() {
  const u = dr.username;
  const el = $("#drawer");
  const c = rowOf(u) || { username: u };
  el.innerHTML = `<div class="none-yet">Đang tải…</div>`;
  let hist, ins;
  try {
    [hist, ins] = await Promise.all([
      api(`/api/channels/${encodeURIComponent(u)}/history?days=${dr.days}`),
      api(`/api/channels/${encodeURIComponent(u)}/insights`),
    ]);
  } catch (e) {
    el.innerHTML = `<div class="none-yet">Không tải được: ${esc(e.message)}</div><button class="btn" id="drClose">Đóng</button>`;
    $("#drClose").onclick = closeDrawer;
    return;
  }
  if (dr.username !== u) return;
  const tile = (k, v, s = "") => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  let insight = "";
  if (ins.empty) {
    insight = '<div class="panel"><div class="none-yet">Chưa có video nào được quét cho kênh này. Dùng <b>Quét video…</b> để lấy danh sách video rồi quay lại đây.</div></div>';
  } else {
    const days = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
    insight =
      `<div class="stat-tiles">` +
      tile("View trung vị", plainNf(ins.views.median), "nửa số video trên mức này") +
      tile("View trung bình", plainNf(ins.views.mean)) +
      tile("Top 10% từ", plainNf(ins.views.p90)) +
      tile("Cao nhất", plainNf(ins.views.max)) +
      tile("Tương tác", ins.er != null ? String(ins.er).replace(".", ",") + "%" : "–") +
      tile("Vượt trội", String(ins.outperformers.length), "≥ 2× trung vị") +
      `</div>` +
      `<div class="panel"><h4>Phân bố view</h4>${Charts.bars(ins.distribution.map((d) => ({ label: d.label, value: d.count })))}</div>` +
      `<div class="panel"><h4>Số video đăng mỗi tuần (12 tuần)</h4>${Charts.columns(ins.weekly.map((w) => ({ label: w.weeks_ago ? `${w.weeks_ago} tuần trước` : "Tuần này", value: w.posts })))}</div>` +
      `<div class="panel"><h4>Giờ đăng hiệu quả</h4>${Charts.heatmap(ins.heatmap)}` +
      (ins.best_slot ? `<div class="muted" style="margin-top:6px">Khung trung bình cao nhất: <b>${days[ins.best_slot.weekday]} ${ins.best_slot.hour}h</b> – ${plainNf(ins.best_slot.avg_views)} view/video (${ins.best_slot.count} video).</div>` : '<div class="muted" style="margin-top:6px">Chưa đủ video cùng khung giờ để kết luận.</div>') +
      `</div>` +
      `<div class="panel"><h4>Top 5 video</h4>${ins.top.map((v) => `<div class="top-video">${v.cover ? `<img class="cover" src="${esc(v.cover)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.visibility='hidden'">` : "<span></span>"}<div><div class="desc" title="${esc(v.description)}"><a href="https://www.tiktok.com/@${esc(c.unique_id || u)}/video/${esc(v.id)}" target="_blank">${esc(v.description || "(không có mô tả)")}</a></div><div class="meta">${fmtDate(v.create_time)} · tim ${plainNf(v.digg)} · bình luận ${plainNf(v.comment)}</div></div><b>${plainNf(v.play)}</b></div>`).join("")}</div>`;
  }
  el.innerHTML =
    `<div class="drawer-head">` +
    (c.avatar ? `<img class="avatar" src="${esc(c.avatar)}" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : '<span class="avatar ph"></span>') +
    `<div><h3>${esc(displayName(c))}${c.verified ? ' <span class="tick">✔</span>' : ""}</h3><div class="sub">${esc(c.nickname || "")}${c.group_name ? " · " + esc(c.group_name) : ""}</div></div>` +
    `<span class="spacer" style="flex:1"></span><button class="icon-btn" id="drClose" aria-label="Đóng" title="Đóng (Esc)">✕</button></div>` +
    `<div class="stat-tiles">` +
    tile("Follow", plainNf(c.followers), c.d_followers ? (c.d_followers > 0 ? "+" : "−") + plainNf(Math.abs(c.d_followers)) : "") +
    tile("Lượt thích", plainNf(c.likes)) +
    tile("Video", plainNf(c.video_count), `${plainNf(c.scanned || 0)} đã quét`) +
    tile("Tổng view", plainNf(c.total_views)) +
    `</div>` +
    `<div class="panel"><h4>Lịch sử <span class="spacer"></span>` +
    seg([["followers", "Follow"], ["likes", "Tim"], ["total_views", "View"], ["video_count", "Video"]], dr.metric, "dmetric") + " " +
    seg([[7, "7 ngày"], [30, "30 ngày"], [90, "90 ngày"], [0, "Tất cả"]], dr.days, "ddays") +
    `</h4><div id="drChart"></div><div class="muted" style="margin-top:4px">${hist.points.length} lần ghi nhận${hist.points.length < 2 ? " – cần cập nhật thêm để vẽ biểu đồ" : ""}.</div></div>` +
    insight +
    `<div class="scan-opts">` +
    `<button class="btn" id="drVideos">▤ Danh sách video</button>` +
    `<button class="btn" id="drQuick">↻ Cập nhật nhanh</button>` +
    `<button class="btn" id="drCsv">⬇ Lịch sử CSV</button>` +
    `<a class="btn" href="https://www.tiktok.com/@${esc(c.unique_id || u)}" target="_blank" rel="noopener" style="text-decoration:none">↗ Mở TikTok</a>` +
    `</div>`;
  dr.stop?.();
  dr.stop = Charts.line($("#drChart"), [{ name: METRIC_LABEL[dr.metric], points: hist.points.map((p) => [p.ts, p[dr.metric]]) }],
    { fmt: plainNf, label: `Lịch sử ${METRIC_LABEL[dr.metric]}`, height: 200 });
  $("#drClose").onclick = closeDrawer;
  $("#drVideos").onclick = () => openUrls([`${location.origin}/videos?u=${encodeURIComponent(u)}`]);
  $("#drQuick").onclick = () => refresh([{ username: u }], { mode: "quick" });
  $("#drCsv").onclick = () => (location.href = `/api/export/history/${encodeURIComponent(u)}.csv`);
  el.focus?.();
}

$("#drawer").addEventListener("click", (e) => {
  const m = e.target.closest("[data-dmetric]");
  if (m) { dr.metric = m.dataset.dmetric; paintDrawer(); return; }
  const d = e.target.closest("[data-ddays]");
  if (d) { dr.days = +d.dataset.ddays; paintDrawer(); }
});
$("#drawer").tabIndex = -1;

// ---------------------------------------------------------------- so sánh

const cmp = { users: [], metric: "followers", days: 30, stop: null };

function openCompare(sel) {
  cmp.users = sel.slice(0, 6).map((c) => c.username);
  $("#cmpTitle").textContent = `So sánh ${cmp.users.length} kênh`;
  $("#dlgCompare").showModal();
  paintCompare();
}

async function paintCompare() {
  $("#cmpMetric").innerHTML = Object.entries(METRIC_LABEL).map(([v, l]) => `<button data-cm="${v}" class="${v === cmp.metric ? "on" : ""}">${l}</button>`).join("");
  $("#cmpRange").innerHTML = [[7, "7 ngày"], [30, "30 ngày"], [90, "90 ngày"], [0, "Tất cả"]].map(([v, l]) => `<button data-cd="${v}" class="${v === cmp.days ? "on" : ""}">${l}</button>`).join("");
  let data;
  try {
    data = await api(`/api/compare?usernames=${encodeURIComponent(cmp.users.join(","))}&metric=${cmp.metric}&days=${cmp.days}`);
  } catch (e) {
    $("#cmpChart").innerHTML = `<div class="none-yet">Không tải được: ${esc(e.message)}</div>`;
    return;
  }
  const names = cmp.users.filter((u) => data.series[u]);
  const series = names.map((u, i) => ({ name: displayName(rowOf(u) || { username: u }), points: data.series[u], color: Charts.PALETTE[i % 6] }));
  cmp.stop?.();
  cmp.stop = Charts.line($("#cmpChart"), series, { fmt: plainNf, height: 280, label: "So sánh kênh" });
  $("#cmpLegend").innerHTML = series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("");
  $("#cmpTable").innerHTML =
    '<table class="mini"><tr><th>Kênh</th><th class="r">Hiện tại</th><th class="r">Đầu kỳ</th><th class="r">Thay đổi</th><th class="r">%</th></tr>' +
    series.map((s) => {
      const p = s.points;
      if (!p.length) return `<tr><td>${esc(s.name)}</td><td class="r" colspan="4">–</td></tr>`;
      const a = p[0][1], b = p[p.length - 1][1], d = b - a;
      return `<tr><td><i style="display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;background:${s.color}"></i>${esc(s.name)}</td><td class="r">${plainNf(b)}</td><td class="r">${plainNf(a)}</td><td class="r"><span class="delta ${d >= 0 ? "up" : "down"}">${d > 0 ? "+" : d < 0 ? "−" : ""}${plainNf(Math.abs(d))}</span></td><td class="r">${a ? ((d / a) * 100).toFixed(1).replace(".", ",") + "%" : "–"}</td></tr>`;
    }).join("") + "</table>";
}
$("#dlgCompare").addEventListener("click", (e) => {
  const m = e.target.closest("[data-cm]");
  if (m) { cmp.metric = m.dataset.cm; paintCompare(); return; }
  const d = e.target.closest("[data-cd]");
  if (d) { cmp.days = +d.dataset.cd; paintCompare(); }
});
$("#cmpClose").onclick = () => $("#dlgCompare").close();
$("#dlgCompare").addEventListener("close", () => { cmp.stop?.(); cmp.stop = null; });

// ---------------------------------------------------------------- chế độ xem đã lưu

function currentView() {
  return {
    q: $("#search").value,
    group: $("#groupFilter").value,
    sort: table.sort,
    hidden: [...table.hiddenCols],
  };
}

function applyView(v) {
  $("#search").value = v.q || "";
  $("#groupFilter").value = v.group || "";
  table.sort = v.sort || null;
  if (Array.isArray(v.hidden)) table.hiddenCols = new Set(v.hidden);
  table.save();
  applyFilter();
  table.render();
  showTab("channels");
}

let savedViews = [];
async function loadViews() {
  try {
    savedViews = (await api("/api/views")).views;
  } catch {}
}

$("#btnViews").onclick = async (e) => {
  const r = e.currentTarget.getBoundingClientRect(); // trước await: sau đó currentTarget là null
  await loadViews();
  const items = [{ header: "Chế độ xem" }];
  if (!savedViews.length) items.push({ icon: "", label: "(chưa có chế độ xem nào)", disabled: true, action() {} });
  for (const v of savedViews) items.push({ icon: "◧", label: v.name, action: () => applyView(v.data) });
  items.push("-", {
    icon: "＋", label: "Lưu bộ lọc, cột và sắp xếp hiện tại…",
    async action() {
      const name = await prompt2("Tên chế độ xem", "", "Lưu lại ô tìm kiếm, nhóm, cột đang hiện và cách sắp xếp.");
      if (!name) return;
      try {
        await api("/api/views", { name, data: currentView() });
        toast(`Đã lưu chế độ xem "${name}"`);
      } catch (err) {
        toast("Lỗi: " + err.message, "err");
      }
    },
  });
  for (const v of savedViews) {
    items.push({
      icon: "✕", label: `Xóa "${v.name}"`, danger: true,
      async action() {
        await api("/api/views/delete", { name: v.name });
        toast(`Đã xóa chế độ xem "${v.name}"`);
      },
    });
  }
  ContextMenu.show(r.left, r.bottom + 4, items);
};

// ---------------------------------------------------------------- nhập file

const importScan = mountScanOptions($("#importScan"), "scan-import");
const importDetect = () => {
  const text = $("#importText").value;
  if (!text.trim()) return ($("#importInfo").textContent = "");
  const csv = /^\s*(username|user|kênh|kenh|channel|link|url)\s*,/i.test(text);
  if (csv) {
    const rows = text.split(/\r?\n/).filter((l) => l.trim()).length - 1;
    $("#importInfo").textContent = `CSV: ${rows} dòng dữ liệu.`;
  } else {
    const { users, shortLinks } = detectCount(text);
    $("#importInfo").textContent = `Nhận dạng được ${users} kênh${shortLinks ? ` + ${shortLinks} link rút gọn` : ""}.`;
  }
};
$("#importText").addEventListener("input", importDetect);
$("#btnImport").onclick = () => {
  $("#importText").value = "";
  importDetect();
  $("#dlgImport").showModal();
};
$("#importCancel").onclick = () => $("#dlgImport").close();
$("#importPick").onclick = () => $("#importFile").click();

async function readImportFile(file) {
  if (!file) return;
  if (file.size > 2_000_000) return toast("File quá lớn (tối đa 2 MB)", "err");
  $("#importText").value = (await file.text()).replace(/^﻿/, "");
  importDetect();
}
$("#importFile").addEventListener("change", (e) => readImportFile(e.target.files[0]));
const drop = $("#importDrop");
for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
drop.addEventListener("drop", (e) => readImportFile(e.dataTransfer.files[0]));

$("#importOk").onclick = async () => {
  const text = $("#importText").value.trim();
  if (!text) return $("#importText").focus();
  const scan = importScan.job();
  if (!scan) return;
  $("#importOk").disabled = true;
  try {
    const r = await api("/api/import/channels", { text, scan });
    const parts = [];
    if (r.added.length) parts.push(`Đã thêm ${r.added.length} kênh`);
    if (r.existed.length) parts.push(`${r.existed.length} kênh đã có`);
    if (r.invalid.length) parts.push(`${r.invalid.length} mục không nhận dạng được`);
    if (r.meta) parts.push(`gán nhóm/ghi chú cho ${r.meta} kênh`);
    toast(parts.join(" · ") || "Không tìm thấy kênh nào", r.added.length ? "" : "err");
    if (!r.invalid.length) $("#dlgImport").close();
    else $("#importText").value = r.invalid.join("\n");
    load();
  } catch (e) {
    toast("Lỗi: " + e.message, "err");
  } finally {
    $("#importOk").disabled = false;
  }
};

// ---------------------------------------------------------------- bảng lệnh

const fold = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");

function buildCommands() {
  const cmds = [
    { label: "Chuyển đến Kênh", group: "Màn hình", run: () => showTab("channels") },
    { label: "Chuyển đến Tổng quan", group: "Màn hình", run: () => showTab("overview") },
    { label: "Chuyển đến Cảnh báo", group: "Màn hình", run: () => showTab("alerts") },
    { label: "Cập nhật tất cả kênh", group: "Hành động", run: () => rowsNow().length && refresh(rowsNow(), QUICK) },
    { label: "Quét video cho các kênh đang chọn (hoặc tất cả)…", group: "Hành động", run: () => { showTab("channels"); $("#btnScan").click(); } },
    { label: "Nhập kênh từ file…", group: "Hành động", run: () => $("#btnImport").click() },
    { label: "Xuất Excel danh sách kênh", group: "Hành động", run: () => exportExcel([]) },
    { label: "Tải bản sao lưu dữ liệu", group: "Hành động", run: () => (location.href = "/api/export/backup") },
    { label: "Mở cài đặt", group: "Hành động", run: () => $("#btnSettings").click() },
    { label: "Xem phím tắt", group: "Hành động", run: () => $("#dlgHelp").showModal() },
    {
      label: "Đổi giao diện sáng / tối", group: "Giao diện",
      run: () => {
        const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
        localStorage.setItem("theme", dark ? "light" : "dark");
        applyLook();
      },
    },
    { label: "Bật / tắt bảng gọn", group: "Giao diện", run: () => { localStorage.setItem("dense", localStorage.getItem("dense") === "1" ? "0" : "1"); applyLook(); } },
  ];
  for (const v of savedViews) cmds.push({ label: `Chế độ xem: ${v.name}`, group: "Chế độ xem", run: () => applyView(v.data) });
  for (const c of rowsNow()) {
    cmds.push({
      label: `${displayName(c)}${c.nickname ? " – " + c.nickname : ""}`, group: "Kênh", key: fold(`${c.username} ${c.unique_id || ""} ${c.nickname || ""}`),
      run: () => openDrawer(c.username),
    });
  }
  return cmds;
}

let paletteEl = null;
async function openPalette() {
  if (paletteEl) return;
  await loadViews();
  const cmds = buildCommands();
  const shade = document.createElement("div");
  shade.className = "palette-shade";
  shade.innerHTML = `<div class="palette" role="dialog" aria-label="Bảng lệnh"><input type="text" placeholder="Gõ tên kênh hoặc lệnh…" aria-label="Tìm lệnh"><ul role="listbox"></ul></div>`;
  document.body.appendChild(shade);
  paletteEl = shade;
  const input = $("input", shade), ul = $("ul", shade);
  let list = [], idx = 0;
  const paint = () => {
    const terms = fold(input.value).split(/\s+/).filter(Boolean);
    list = cmds.filter((c) => terms.every((t) => (c.key || fold(c.label)).includes(t) || fold(c.label).includes(t))).slice(0, 40);
    idx = Math.min(idx, Math.max(0, list.length - 1));
    ul.innerHTML = list.length
      ? list.map((c, i) => `<li role="option" data-i="${i}" aria-selected="${i === idx}"><span>${esc(c.label)}</span><span class="grp">${esc(c.group)}</span></li>`).join("")
      : '<div class="none-yet">Không có kết quả.</div>';
    ul.children[idx]?.scrollIntoView?.({ block: "nearest" });
  };
  const close = () => { shade.remove(); paletteEl = null; };
  const run = (i) => { const c = list[i]; if (!c) return; close(); c.run(); };
  input.addEventListener("input", () => { idx = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { idx = Math.min(list.length - 1, idx + 1); paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { idx = Math.max(0, idx - 1); paint(); e.preventDefault(); }
    else if (e.key === "Enter") { run(idx); e.preventDefault(); }
    else if (e.key === "Escape") { close(); e.stopPropagation(); }
  });
  ul.addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) run(+li.dataset.i); });
  shade.addEventListener("mousedown", (e) => { if (e.target === shade) close(); });
  paint();
  input.focus();
}
$("#btnPalette").onclick = openPalette;
$("#btnHelp").onclick = () => $("#dlgHelp").showModal();
$("#helpClose").onclick = () => $("#dlgHelp").close();

// ---------------------------------------------------------------- phím tắt toàn cục

$("#btnRetryInterrupted").onclick = () => {
  const stuck = rowsNow().filter((c) => c.status === "error" && (c.message || "").startsWith("Bị dừng"));
  if (stuck.length) refresh(stuck, QUICK);
};

addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openPalette();
    return;
  }
  if (e.key === "Escape" && dr.username && !dialogOpen() && !paletteEl) {
    closeDrawer();
    return;
  }
  if (typing(e) || dialogOpen() || paletteEl || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "?") { e.preventDefault(); $("#dlgHelp").showModal(); }
  else if (e.key === "1") showTab("channels");
  else if (e.key === "2") showTab("overview");
  else if (e.key === "3") showTab("alerts");
});

// ---------------------------------------------------------------- khởi động

addEventListener("hashchange", () => showTab(location.hash.slice(1)));
loadViews();
pollAlerts();
setInterval(pollAlerts, 15000);
if (location.hash) showTab(location.hash.slice(1));
