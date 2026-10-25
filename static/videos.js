const username = new URLSearchParams(location.search).get("u") || "";
let channel = null;
const videoUrl = (v) => `https://www.tiktok.com/@${channel?.unique_id || username}/video/${v.id}`;
const er = (v) => (v.play ? ((v.digg + v.comment + v.share + v.collect) / v.play) * 100 : null);
const dView = (v) => (v.prev_play != null ? v.play - v.prev_play : null);

const columns = [
  { key: "stt", label: "#", align: "r", nosort: true, fixed: true, render: (r, i) => `<span class="muted">${i + 1}</span>` },
  { key: "cover", label: "Ảnh", nosort: true, render: (r) => (r.cover ? `<img class="cover" src="${esc(r.cover)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.visibility='hidden'">` : "") },
  { key: "link", label: "Link video", fixed: true, get: (r) => r.id, render: (r) => `<a class="vlink" href="${esc(videoUrl(r))}" target="_blank" title="${esc(videoUrl(r))}">…/video/${esc(r.id)}</a>` },
  { key: "description", label: "Mô tả", render: (r) => `<span class="wrap-cell" style="display:inline-block;vertical-align:bottom;max-width:320px" title="${esc(r.description)}">${esc(r.description) || '<span class="muted">(không có mô tả)</span>'}</span>` },
  { key: "create_time", label: "Ngày đăng", render: (r) => fmtDate(r.create_time, true) },
  { key: "duration", label: "Thời lượng", align: "r", render: (r) => fmtDuration(r.duration) },
  { key: "play", label: "View", align: "r", render: (r) => fmtNum(r.play) + fmtDelta(dView(r)) },
  { key: "d_view", label: "+View", align: "r", hidden: true, title: "Tăng view so với lần quét trước", get: dView, render: (r) => fmtDelta(dView(r)) || '<span class="muted">–</span>' },
  { key: "digg", label: "Tim", align: "r", render: (r) => fmtNum(r.digg) },
  { key: "comment", label: "Bình luận", align: "r", render: (r) => fmtNum(r.comment) },
  { key: "share", label: "Chia sẻ", align: "r", render: (r) => fmtNum(r.share) },
  { key: "collect", label: "Lưu", align: "r", title: "Lượt lưu yêu thích", render: (r) => fmtNum(r.collect) },
  { key: "er", label: "Tương tác %", align: "r", title: "(Tim + bình luận + chia sẻ + lưu) / view", get: er, render: (r) => (er(r) != null ? er(r).toFixed(2).replace(".", ",") + "%" : '<span class="muted">–</span>') },
  { key: "music", label: "Nhạc", hidden: true, render: (r) => `<span class="wrap-cell" style="display:inline-block;vertical-align:bottom;max-width:200px" title="${esc(r.music)}">${esc(r.music)}</span>` },
  { key: "updated_at", label: "Cập nhật", hidden: true, render: (r) => fmtAgo(r.updated_at) },
];

let medianPlay = 0;
const median = (a) => {
  if (!a.length) return 0;
  const s = [...a].sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

const table = new DataTable({
  el: $("#table"),
  columns,
  rowKey: (r) => r.id,
  storageKey: "videos-table",
  // Outperformer: at least double the channel median (needs >= 5 videos for the median to be meaningful).
  rowClass: (r) => (table.rows.length >= 5 && medianPlay && r.play >= 2 * medianPlay ? "row-star" : ""),
  onOpen: (r) => openUrls([videoUrl(r)]),
  onContextMenu: (e, sel) => showMenu(e.clientX, e.clientY, sel),
  onSelectionChange: updateStatusbar,
});
table.emptyText = "Chưa có video nào – đang quét hoặc kênh chưa có video.";

function showMenu(x, y, sel) {
  const n = sel.length;
  ContextMenu.show(x, y, [
    { header: n === 1 ? "1 video" : `${n} video đã chọn` },
    { icon: "↗", label: n === 1 ? "Mở video" : `Mở ${n} video`, hint: "Enter", disabled: n > 30, action: () => openUrls(sel.map(videoUrl)) },
    { icon: "↻", label: n === 1 ? "Cập nhật view video này" : `Cập nhật view ${n} video này`, hint: "F5", action: () => updateVideos(sel) },
    "-",
    { icon: "🔗", label: n === 1 ? "Sao chép link" : `Sao chép ${n} link`, hint: "Ctrl+C", action: () => copyText(sel.map(videoUrl).join("\n"), `Đã sao chép ${n} link`) },
    { icon: "⧉", label: "Sao chép mô tả", action: () => copyText(sel.map((v) => v.description).join("\n")) },
    { icon: "▦", label: "Sao chép số liệu (dán vào Excel)", action: () => copyStats(sel) },
    "-",
    { icon: "☐", label: "Chọn tất cả", hint: "Ctrl+A", action: () => table.selectAll() },
  ]);
}

function copyStats(rows) {
  const head = ["Link", "Mô tả", "Ngày đăng", "View", "Tim", "Bình luận", "Chia sẻ", "Lưu"];
  const lines = rows.map((v) => [videoUrl(v), (v.description || "").replace(/\s+/g, " "), new Date(v.create_time * 1000).toLocaleString("vi-VN"), v.play, v.digg, v.comment, v.share, v.collect].join("\t"));
  copyText([head.join("\t"), ...lines].join("\n"), `Đã sao chép số liệu ${rows.length} video`);
}

let summaryKey = "";
function renderSummary() {
  const rows = table.view;
  const key = rows.length + ":" + rows.reduce((a, r) => a + r.play, 0) + ":" + (rows[0]?.id || "");
  if (key === summaryKey) return;
  summaryKey = key;
  const plays = rows.map((r) => r.play || 0);
  const total = plays.reduce((a, b) => a + b, 0);
  const inter = rows.reduce((a, r) => a + r.digg + r.comment + r.share + r.collect, 0);
  const times = rows.map((r) => r.create_time).filter(Boolean);
  const weeks = times.length > 1 ? Math.max(1, (Math.max(...times) - Math.min(...times)) / 604800) : 0;
  const best = rows.reduce((b, r) => (!b || r.play > b.play ? r : b), null);
  const card = (k, v, s = "") => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  $("#summary").innerHTML =
    card("Video", fmtNum(rows.length)) +
    card("Tổng view", fmtNum(total)) +
    card("View trung vị", fmtNum(Math.round(median(plays))), "nửa số video trên mức này") +
    card("Cao nhất", fmtNum(best?.play ?? null), best ? `<a class="vlink" href="${esc(videoUrl(best))}" target="_blank">${esc((best.description || "").slice(0, 40) || "…/video/" + best.id)}</a>` : "") +
    card("Tương tác", total ? (inter / total * 100).toFixed(2).replace(".", ",") + "%" : "–") +
    card("Đăng / tuần", weeks ? (rows.length / weeks).toFixed(1).replace(".", ",") : "–");
  renderAnalysis(rows);
}

let stopTimeline = null;
function renderAnalysis(rows) {
  if (!$("#analysis").open) return;
  stopTimeline?.();
  const pts = rows.filter((r) => r.create_time).map((r) => [r.create_time, r.play]).sort((a, b) => a[0] - b[0]);
  stopTimeline = Charts.line($("#anTimeline"), [{ name: "View", points: pts }], {
    fmt: Charts.full, height: 190, label: "View theo ngày đăng", empty: "Chưa có video để vẽ.",
  });
  const buckets = [["<1k", 1e3], ["1k–10k", 1e4], ["10k–100k", 1e5], ["100k–1M", 1e6], ["≥1M", Infinity]];
  const counts = buckets.map(([label, max], i) => ({
    label,
    value: rows.filter((r) => r.play < max && r.play >= (i ? buckets[i - 1][1] : -Infinity)).length,
  }));
  $("#anDist").innerHTML = Charts.bars(counts);
  const cells = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => []));
  for (const r of rows) {
    if (!r.create_time) continue;
    const d = new Date(r.create_time * 1000);
    cells[(d.getDay() + 6) % 7][d.getHours()].push(r.play || 0);
  }
  $("#anHeat").innerHTML = Charts.heatmap(
    cells.map((row) => row.map((c) => ({ count: c.length, avg_views: c.length ? Math.round(c.reduce((a, b) => a + b, 0) / c.length) : 0 })))
  );
}
// The analytics section starts collapsed to leave room for the video table; the user's choice is remembered.
try {
  $("#analysis").open = localStorage.getItem("analysis-open") === "1";
} catch {}
$("#analysis").addEventListener("toggle", () => {
  try {
    localStorage.setItem("analysis-open", $("#analysis").open ? "1" : "0");
  } catch {}
  summaryKey = "";
  renderSummary();
});

function updateStatusbar(sel) {
  renderSummary();
  const rows = sel.length ? sel : table.view;
  const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
  const views = sum("play");
  $("#statusbar").innerHTML =
    (sel.length ? `Đã chọn <b>${sel.length}</b>/${table.view.length} video` : `<b>${table.view.length}</b> video`) +
    `<span>View: <b>${fmtNum(views)}</b></span>` +
    `<span>TB/video: <b>${fmtNum(rows.length ? Math.round(views / rows.length) : null)}</b></span>` +
    `<span>Tim: <b>${fmtNum(sum("digg"))}</b></span>` +
    `<span>Bình luận: <b>${fmtNum(sum("comment"))}</b></span>` +
    `<span>Chia sẻ: <b>${fmtNum(sum("share"))}</b></span>` +
    `<span>Lưu: <b>${fmtNum(sum("collect"))}</b></span>`;
}

function renderHead(c, total) {
  document.title = `@${c.unique_id || c.username} – ttwatch`;
  const url = `https://www.tiktok.com/@${c.unique_id || c.username}`;
  $("#chHead").innerHTML =
    (c.avatar ? `<img class="avatar" src="${esc(c.avatar)}" referrerpolicy="no-referrer">` : '<span class="avatar ph" style="width:56px;height:56px"></span>') +
    `<div><div class="ch-title">${esc(c.nickname || c.username)}${c.verified ? '<span class="tick">✔</span>' : ""}
       <a class="uname muted" style="font-size:14px;font-weight:500;margin-left:6px" href="${esc(url)}" target="_blank">@${esc(c.unique_id || c.username)} ↗</a></div>
     <div class="ch-stats">
       <span>Follow <b>${fmtNum(c.followers)}</b></span>
       <span>Lượt thích <b>${fmtNum(c.likes)}</b></span>
       <span>Tổng view <b>${fmtNum(total)}</b></span>
       <span>Video <b>${fmtNum(c.video_count)}</b></span>
       <span>Quét gần nhất: <b>${c.last_scan_at ? `${fmtDate(c.last_scan_at, true)} (${esc(c.last_scan_label || "")})` : "chưa"}</b></span>
       <span>Quét toàn bộ lần cuối: <b>${c.full_scan_at ? fmtDate(c.full_scan_at, true) : "chưa"}</b></span>
       ${c.message ? `<span style="color:var(--down)">${esc(c.message)}</span>` : ""}
     </div></div>`;
}

function renderWorker(w) {
  const c = w.current;
  const mine = c?.username === username.toLowerCase();
  $("#worker").innerHTML = mine
    ? c.total
      ? `<span class="spin"></span>Đang cập nhật view · ${nf.format(c.videos)}/${nf.format(c.total)} video`
      : `<span class="spin"></span>Đang quét kênh này${c.videos ? ` · ${nf.format(c.videos)} video` : "…"}`
    : channel?.status === "queued"
      ? w.pause ? "⏸ TikTok đang giới hạn, tool nghỉ một lúc rồi sẽ quét kênh này" : '<span class="spin"></span>Đang chờ đến lượt quét'
      : "";
}

let lastJson = "";
async function load() {
  try {
    const data = await api(`/api/channels/${encodeURIComponent(username)}/videos`);
    channel = data.channel;
    renderWorker(data.worker);
    const json = JSON.stringify([data.channel, data.videos]);
    if (json !== lastJson) {
      lastJson = json;
      renderHead(channel, data.videos.reduce((a, v) => a + v.play, 0));
      medianPlay = median(data.videos.map((v) => v.play || 0));
      summaryKey = "";
      table.setRows(data.videos);
      if ($("#period").value === "last") applyFilter();
    }
  } catch (e) {
    $("#chHead").innerHTML = `<div class="ch-title">⚠ ${esc(e.message)}</div>`;
  }
}

function applyFilter() {
  const q = $("#search").value.trim().toLowerCase();
  const period = $("#period").value;
  $("#rangeBox").style.display = period === "range" ? "" : "none";
  let since = 0, until = Infinity, lastScan = null;
  if (period === "last") lastScan = Math.max(0, ...table.rows.map((v) => v.updated_at || 0));
  else if (period === "range") {
    const from = $("#fromDate").value, to = $("#toDate").value;
    if (from) since = new Date(from + "T00:00:00").getTime() / 1000;
    if (to) until = new Date(to + "T23:59:59").getTime() / 1000;
  } else if (+period) since = Date.now() / 1000 - +period * 86400;
  table.setFilter(
    (v) =>
      v.create_time >= since &&
      v.create_time <= until &&
      (lastScan === null || v.updated_at === lastScan) &&
      (!q || (v.description + " " + v.music).toLowerCase().includes(q))
  );
}

async function updateVideos(sel) {
  await api("/api/channels/refresh", { usernames: [username], job: { mode: "videos", ids: sel.map((v) => v.id) } });
  toast(`Đang cập nhật view ${sel.length} video – số mới sẽ tự hiện khi xong`);
  load();
}

async function refresh(job) {
  const r = await api("/api/channels/refresh", { usernames: [username], job });
  toast(r.queued ? "Đã thêm vào hàng đợi quét" : "Kênh này đã có trong hàng đợi");
  load();
}

$("#search").addEventListener("input", applyFilter);
$("#period").addEventListener("change", applyFilter);
$("#fromDate").addEventListener("change", applyFilter);
$("#toDate").addEventListener("change", applyFilter);
$("#btnQuick").onclick = () => refresh({ mode: "quick" });
$("#btnScan").onclick = async () => {
  const job = await scanDialog(`Quét video @${channel?.unique_id || username}`);
  if (job) {
    refresh(job);
    $("#period").value = "last";
    applyFilter();
  }
};
$("#btnCopyAll").onclick = () => copyText(table.view.map(videoUrl).join("\n"), `Đã sao chép ${table.view.length} link`);
$("#btnExport").onclick = () => (location.href = `/api/export/videos/${encodeURIComponent(username)}.xlsx`);
$("#btnCsv").onclick = () => (location.href = `/api/export/videos/${encodeURIComponent(username)}.csv`);
$("#btnColumns").onclick = (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  table.showColumnMenu(r.left, r.bottom + 4);
};
setCompactToggle($("#btnCompact"), () => table.render());

bindTableKeys(table, {
  Enter: (sel) => sel.length <= 30 && openUrls(sel.map(videoUrl)),
  F5: updateVideos,
  copy: (sel) => copyText(sel.map(videoUrl).join("\n"), `Đã sao chép ${sel.length} link`),
});

$("#search").value = new URLSearchParams(location.search).get("q") || ""; // e.g. a hashtag clicked in the channel detail
applyFilter();
load();
setInterval(load, 3000);
