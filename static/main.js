const tiktokUrl = (c) => `https://www.tiktok.com/@${c.unique_id || c.username}`;
const videosUrl = (c) => `${location.origin}/videos?u=${encodeURIComponent(c.username)}`;
let worker = {};
let sparks = {}; // username -> [follow...] cho cột xu hướng
const pendingDelete = new Set(); // kênh đã ẩn, đang chờ hết thời gian hoàn tác mới xóa thật
let firstLoad = true;

// Gợi ý cách xử lý cho các lỗi hay gặp; thông báo gốc vẫn hiện nguyên văn.
function errorHint(msg) {
  const m = (msg || "").toLowerCase();
  if (m.includes("captcha")) return "TikTok yêu cầu xác minh. Bật \"Hiện cửa sổ trình duyệt\" trong Cài đặt, giải captcha một lần rồi quét lại.";
  if (m.includes("không tồn tại")) return "Kênh không tồn tại hoặc bị khóa – kiểm tra lại username.";
  if (m.includes("bị dừng")) return "Lần chạy trước bị tắt giữa chừng – hãy cập nhật lại.";
  if (m.includes("timeout") || m.includes("net::") || m.includes("đã thử")) return "Lỗi mạng hoặc TikTok phản hồi chậm – thử lại sau.";
  if (m.includes("hồ sơ trình duyệt")) return "Một cửa sổ trình duyệt khác đang giữ hồ sơ của tool – hãy tắt nó rồi thử lại.";
  return "";
}

function statusBadge(c) {
  if (c.status === "running") {
    const w = worker.current?.username === c.username ? worker.current : null;
    if (w?.total) return `<span class="badge run"><span class="spin"></span>Cập nhật view · ${nf.format(w.videos)}/${nf.format(w.total)}</span>`;
    return `<span class="badge run"><span class="spin"></span>Đang quét${w?.videos ? ` · ${nf.format(w.videos)} video` : "…"}</span>`;
  }
  if (c.status === "queued") return '<span class="badge">Đang chờ</span>';
  if (c.status === "error") {
    const hint = errorHint(c.message);
    return `<span class="badge err" title="${esc(c.message + (hint ? "\n\n" + hint : ""))}">⚠ ${esc(c.message || "Lỗi")}</span>`;
  }
  if (c.message) return `<span class="badge" title="${esc(c.message)}">ⓘ ${esc(c.message)}</span>`;
  return '<span class="badge ok">✓ Xong</span>';
}

const columns = [
  { key: "stt", label: "#", align: "r", nosort: true, fixed: true, render: (r, i) => `<span class="muted">${i + 1}</span>` },
  {
    key: "username", label: "Username", fixed: true,
    get: (r) => (r.unique_id || r.username).toLowerCase(),
    render: (r) =>
      `<div class="user-cell">${r.avatar ? `<img class="avatar" src="${esc(r.avatar)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.visibility='hidden'">` : '<span class="avatar ph"></span>'}` +
      `<a class="uname" href="${esc(tiktokUrl(r))}" target="_blank">@${esc(r.unique_id || r.username)}</a></div>`,
  },
  { key: "nickname", label: "Tên kênh", render: (r) => `<span class="wrap-cell" style="display:inline-block;vertical-align:bottom">${esc(r.nickname) || '<span class="muted">–</span>'}</span>${r.verified ? '<span class="tick" title="Tick xanh">✔</span>' : ""}` },
  { key: "followers", label: "Follow", align: "r", title: "Số người theo dõi (kèm mức tăng so với lần cập nhật trước)", render: (r) => fmtNum(r.followers) + fmtDelta(r.d_followers) },
  {
    key: "trend", label: "Xu hướng 30 ngày", title: "Biến động follow trong 30 ngày qua (sắp xếp theo mức tăng)",
    get: (r) => { const v = sparks[r.username]; return v ? v[v.length - 1] - v[0] : null; },
    render: (r) => Charts.spark(sparks[r.username]),
  },
  { key: "d_followers", label: "+Follow", align: "r", hidden: true, title: "Tăng follow so với lần cập nhật trước", render: (r) => fmtDelta(r.d_followers) || '<span class="muted">–</span>' },
  { key: "likes", label: "Lượt thích", align: "r", title: "Tổng tim của kênh", render: (r) => fmtNum(r.likes) + fmtDelta(r.d_likes) },
  { key: "total_views", label: "Tổng view", align: "r", title: "Tổng view của các video đã quét", render: (r) => fmtNum(r.total_views) + fmtDelta(r.d_views) },
  { key: "d_views", label: "+View", align: "r", hidden: true, title: "Tăng view so với lần cập nhật trước", render: (r) => fmtDelta(r.d_views) || '<span class="muted">–</span>' },
  {
    key: "video_count", label: "Số video", align: "r", title: "Số video đã quét / số video kênh",
    render: (r) => (r.video_count != null && r.scanned < r.video_count ? `<span class="muted">${nf.format(r.scanned)}/</span>` : "") + fmtNum(r.video_count),
  },
  { key: "avg_views", label: "View TB/video", align: "r", render: (r) => fmtNum(r.avg_views) },
  { key: "er", label: "Tương tác %", align: "r", title: "(Tim + bình luận + chia sẻ + lưu) / view của các video", render: (r) => (r.er != null ? r.er.toFixed(2).replace(".", ",") + "%" : '<span class="muted">–</span>') },
  { key: "top_views", label: "View cao nhất", align: "r", title: "View của video cao nhất", render: (r) => fmtNum(r.top_views) },
  { key: "posts_7d", label: "Video 7 ngày", align: "r", title: "Số video đăng trong 7 ngày qua", render: (r) => fmtNum(r.posts_7d) },
  { key: "posts_30d", label: "Video 30 ngày", align: "r", hidden: true, render: (r) => fmtNum(r.posts_30d) },
  { key: "views_30d", label: "View 30 ngày", align: "r", title: "Tổng view của các video đăng trong 30 ngày qua", render: (r) => fmtNum(r.views_30d) },
  { key: "last_post", label: "Đăng gần nhất", render: (r) => `<span title="${r.last_post ? fmtDate(r.last_post, true) : ""}">${fmtAgo(r.last_post)}</span>` },
  { key: "following", label: "Following", align: "r", hidden: true, render: (r) => fmtNum(r.following) },
  { key: "group_name", label: "Nhóm", render: (r) => (r.group_name ? `<span class="tag">${esc(r.group_name)}</span>` : "") },
  { key: "note", label: "Ghi chú", render: (r) => `<span class="wrap-cell" style="display:inline-block;vertical-align:bottom" title="${esc(r.note)}">${esc(r.note)}</span>` },
  { key: "bio", label: "Bio", hidden: true, render: (r) => `<span class="wrap-cell" style="display:inline-block;vertical-align:bottom" title="${esc(r.bio)}">${esc(r.bio)}</span>` },
  { key: "bio_link", label: "Link bio", hidden: true, render: (r) => (r.bio_link ? `<a href="${esc(/^https?:/.test(r.bio_link) ? r.bio_link : "https://" + r.bio_link)}" target="_blank">${esc(r.bio_link)}</a>` : "") },
  { key: "created_at", label: "Ngày tạo kênh", hidden: true, render: (r) => fmtDate(r.created_at) },
  { key: "added_at", label: "Ngày thêm", hidden: true, render: (r) => fmtDate(r.added_at, true) },
  { key: "updated_at", label: "Cập nhật", render: (r) => `<span title="${r.updated_at ? fmtDate(r.updated_at, true) : ""}">${fmtAgo(r.updated_at)}</span>` },
  { key: "status", label: "Trạng thái", get: (r) => r.status + r.message, render: statusBadge },
];

const table = new DataTable({
  el: $("#table"),
  columns,
  rowKey: (r) => r.username,
  storageKey: "channels-table",
  rowClass: (r) => (r.status === "error" && !r.updated_at ? "err" : ""),
  onOpen: (r) => openUrls([videosUrl(r)]),
  onContextMenu: (e, sel) => showMenu(e.clientX, e.clientY, sel),
  onSelectionChange: updateStatusbar,
});
table.emptyText =
  '<div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:6px">Chưa có kênh nào</div>' +
  "Dán link hoặc username vào ô phía trên rồi bấm <b>Thêm kênh</b>, hoặc dùng <b>Nhập</b> để thêm từ file.<br>" +
  '<span class="muted">Tool chỉ đọc trang công khai của TikTok. Bấm <kbd>?</kbd> để xem phím tắt.</span>';

function showMenu(x, y, sel) {
  const n = sel.length;
  const names = sel.map((c) => c.unique_id || c.username);
  const label = n === 1 ? `@${names[0]}` : `${n} kênh đã chọn`;
  ContextMenu.show(x, y, [
    { header: label },
    { icon: "↗", label: n === 1 ? "Mở kênh này" : `Mở ${n} kênh`, action: () => openUrls(sel.map(tiktokUrl)) },
    { icon: "▤", label: n === 1 ? "Mở danh sách video" : `Mở danh sách video (${n} tab)`, hint: "Enter", action: () => openUrls(sel.map(videosUrl)) },
    { icon: "📈", label: "Biểu đồ và phân tích", hint: "Space", action: () => openDrawer(sel[0]) },
    { icon: "⇄", label: "So sánh các kênh đã chọn", disabled: n < 2 || n > 6, action: () => openCompare(sel) },
    "-",
    { icon: "↻", label: "Cập nhật nhanh", hint: "F5", action: () => refresh(sel, QUICK) },
    { icon: "⟳", label: "Quét video theo số lượng / ngày…", action: () => scanChannels(sel) },
    { icon: "⟲", label: "Quét lại toàn bộ video", action: () => refresh(sel, { mode: "scan" }) },
    "-",
    { icon: "⧉", label: n === 1 ? "Sao chép username" : "Sao chép các username", hint: "Ctrl+C", action: () => copyText(names.join("\n")) },
    { icon: "🔗", label: n === 1 ? "Sao chép link kênh" : "Sao chép các link kênh", action: () => copyText(sel.map(tiktokUrl).join("\n")) },
    { icon: "▦", label: "Sao chép số liệu (dán vào Excel)", action: () => copyStats(sel) },
    "-",
    { icon: "#", label: "Gắn nhóm…", action: () => editGroup(sel) },
    { icon: "✎", label: "Ghi chú…", action: () => editNote(sel) },
    { icon: "⬇", label: "Xuất Excel các kênh này", action: () => exportExcel(sel) },
    "-",
    { icon: "✕", label: n === 1 ? "Xóa kênh" : `Xóa ${n} kênh`, hint: "Del", danger: true, action: () => removeChannels(sel) },
  ]);
}

// ---------------------------------------------------------------- dữ liệu

let lastJson = "";
async function load() {
  try {
    const data = await api("/api/channels");
    worker = data.worker;
    renderWorker();
    renderInterrupted(data.interrupted || 0);
    const rows = data.channels.filter((c) => !pendingDelete.has(c.username));
    const json = JSON.stringify([rows, [...pendingDelete]]);
    if (json !== lastJson) {
      lastJson = json;
      window.channelRows = rows;
      table.setRows(rows);
      updateGroups(rows);
    }
    firstLoad = false;
  } catch (e) {
    $("#worker").innerHTML = '<span style="color:var(--down)">⚠ Tool đã tắt – hãy mở lại file ttwatch.exe</span>';
  }
}

function renderInterrupted(n) {
  const b = $("#bannerInterrupted");
  b.hidden = !n;
  if (n) $("#bannerText").textContent = `${n} kênh bị dừng giữa chừng ở lần chạy trước (tool bị tắt khi đang quét).`;
}

async function loadSparks() {
  try {
    sparks = await api("/api/sparklines?days=30");
    table.render();
  } catch {}
}

function renderWorker() {
  const c = worker.current;
  if (!c && !worker.queue) {
    $("#worker").innerHTML = "";
    return;
  }
  const rest = worker.queue - (c ? 1 : 0);
  $("#worker").innerHTML =
    `<span class="spin"></span>` +
    (c
      ? `<span title="${esc(c.label)}">${c.total ? "Đang cập nhật view" : "Đang quét"} <b>@${esc(c.username)}</b>` +
        (c.total ? ` · ${nf.format(c.videos)}/${nf.format(c.total)} video` : c.videos ? ` · ${nf.format(c.videos)} video` : "") +
        "</span>"
      : "Đang chuẩn bị…") +
    (rest > 0 ? ` · còn ${rest} kênh chờ` : "");
}

function updateStatusbar(sel) {
  const rows = sel.length ? sel : table.view;
  const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
  $("#statusbar").innerHTML =
    (sel.length ? `Đã chọn <b>${sel.length}</b>/${table.view.length} kênh` : `<b>${table.view.length}</b> kênh`) +
    `<span>Follow: <b>${fmtNum(sum("followers"))}</b></span>` +
    `<span>Lượt thích: <b>${fmtNum(sum("likes"))}</b></span>` +
    `<span>Tổng view: <b>${fmtNum(sum("total_views"))}</b></span>` +
    `<span>Video: <b>${fmtNum(sum("video_count"))}</b></span>` +
    `<span class="muted">Chuột phải để xem menu · kéo chuột / Shift / Ctrl để chọn nhiều · nhấp đúp để mở danh sách video</span>`;
}

function updateGroups(rows) {
  const groups = [...new Set(rows.map((r) => r.group_name).filter(Boolean))].sort();
  const sel = $("#groupFilter");
  const cur = sel.value;
  const hasNone = rows.some((r) => !r.group_name);
  sel.innerHTML =
    '<option value="">Tất cả nhóm</option>' +
    (groups.length && hasNone ? '<option value="__none__">(Chưa gắn nhóm)</option>' : "") +
    groups.map((g) => `<option>${esc(g)}</option>`).join("");
  sel.value = groups.includes(cur) || (cur === "__none__" && hasNone) ? cur : "";
  $("#groupList").innerHTML = groups.map((g) => `<option value="${esc(g)}">`).join("");
  renderChips(rows, groups, hasNone);
}

// Chip nhóm: lọc nhanh bằng một cú bấm; chuột phải để đổi tên hoặc bỏ nhóm cho cả nhóm.
function renderChips(rows, groups, hasNone) {
  const box = $("#groupChips");
  box.hidden = groups.length === 0;
  if (!groups.length) return;
  const cur = $("#groupFilter").value;
  const count = (g) => rows.filter((r) => r.group_name === g).length;
  const chip = (value, label, n) =>
    `<button class="chip" data-g="${esc(value)}" aria-pressed="${cur === value}">${esc(label)}<span class="n">${n}</span></button>`;
  box.innerHTML =
    chip("", "Tất cả", rows.length) +
    groups.map((g) => chip(g, g, count(g))).join("") +
    (hasNone ? chip("__none__", "Chưa gắn nhóm", rows.filter((r) => !r.group_name).length) : "");
}

$("#groupChips").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  $("#groupFilter").value = b.dataset.g;
  applyFilter();
  renderChips(rowsNow(), [...new Set(rowsNow().map((r) => r.group_name).filter(Boolean))].sort(), rowsNow().some((r) => !r.group_name));
});

$("#groupChips").addEventListener("contextmenu", (e) => {
  const b = e.target.closest(".chip");
  if (!b || !b.dataset.g || b.dataset.g === "__none__") return;
  e.preventDefault();
  const g = b.dataset.g;
  const members = () => rowsNow().filter((r) => r.group_name === g).map((r) => r.username);
  ContextMenu.show(e.clientX, e.clientY, [
    { header: `Nhóm "${g}" (${members().length} kênh)` },
    {
      icon: "✎", label: "Đổi tên nhóm…",
      async action() {
        const v = await prompt2(`Đổi tên nhóm "${g}"`, g, "Gộp vào nhóm khác bằng cách nhập tên nhóm đó.");
        if (!v || v === g) return;
        await api("/api/channels/meta", { usernames: members(), group_name: v });
        if ($("#groupFilter").value === g) $("#groupFilter").value = v;
        toast(`Đã đổi tên nhóm thành "${v}"`);
        lastJson = "";
        load();
      },
    },
    {
      icon: "✕", label: "Bỏ nhóm này khỏi các kênh", danger: true,
      async action() {
        await api("/api/channels/meta", { usernames: members(), group_name: "" });
        if ($("#groupFilter").value === g) $("#groupFilter").value = "";
        toast(`Đã bỏ nhóm "${g}" (các kênh vẫn còn)`);
        lastJson = "";
        load();
      },
    },
  ]);
});

function rowsNow() {
  return window.channelRows || [];
}

function applyFilter() {
  const q = $("#search").value.trim().toLowerCase();
  const g = $("#groupFilter").value;
  table.setFilter((r) => {
    if (g === "__none__" ? r.group_name : g && r.group_name !== g) return false;
    if (!q) return true;
    return [r.username, r.nickname, r.note, r.bio, r.group_name].some((s) => (s || "").toLowerCase().includes(q));
  });
}

// ---------------------------------------------------------------- hành động

const USER_RE = /^@?[A-Za-z0-9._]{2,24}$/;
function detectCount(text) {
  const set = new Set();
  let shortLinks = 0;
  for (const tok of text.split(/[\s,;]+/)) {
    const t = tok.trim();
    if (!t) continue;
    const m = t.match(/tiktok\.com\/@([A-Za-z0-9._]{2,24})/i);
    if (m) set.add(m[1].toLowerCase());
    else if (/(vt|vm)\.tiktok\.com\/\w+|tiktok\.com\/t\/\w+/i.test(t)) shortLinks++;
    else if (USER_RE.test(t)) set.add(t.replace(/^@/, "").toLowerCase());
  }
  return { users: set.size, shortLinks };
}

$("#input").addEventListener("input", () => {
  const { users, shortLinks } = detectCount($("#input").value);
  $("#detect").innerHTML = users || shortLinks
    ? `Nhận dạng được <b>${users}</b> kênh${shortLinks ? ` + ${shortLinks} link rút gọn` : ""}`
    : "Ctrl + Enter để thêm nhanh";
});
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) addChannels();
});
$("#btnAdd").onclick = addChannels;

const addScan = mountScanOptions($("#addScan"), "scan-add");

async function addChannels() {
  const text = $("#input").value.trim();
  if (!text) return $("#input").focus();
  const scan = addScan.job();
  if (!scan) return;
  $("#btnAdd").disabled = true;
  try {
    const r = await api("/api/channels", { text, scan });
    const parts = [];
    if (r.added.length) parts.push(`Đã thêm ${r.added.length} kênh – quét ${addScan.label()}`);
    if (r.existed.length) parts.push(`${r.existed.length} kênh đã có sẵn`);
    if (r.invalid.length) parts.push(`${r.invalid.length} mục không nhận dạng được`);
    toast(parts.join(" · ") || "Không tìm thấy username nào", r.added.length ? "" : "err");
    $("#input").value = r.invalid.join("\n");
    $("#input").dispatchEvent(new Event("input"));
    await load();
  } catch (e) {
    toast("Lỗi: " + e.message, "err");
  } finally {
    $("#btnAdd").disabled = false;
  }
}

const QUICK = { mode: "quick" };

async function refresh(sel, job) {
  const r = await api("/api/channels/refresh", { usernames: sel.map((c) => c.username), job });
  toast(r.queued ? `Đã thêm ${r.queued} kênh vào hàng đợi` : "Các kênh này đã có trong hàng đợi");
  load();
}

async function scanChannels(sel) {
  if (!sel.length) return;
  const job = await scanDialog(sel.length === 1 ? `Quét video @${sel[0].unique_id || sel[0].username}` : `Quét video ${sel.length} kênh`);
  if (job) refresh(sel, job);
}

// Ẩn ngay, chỉ xóa thật sau UNDO_MS để còn hoàn tác được (xóa kênh kéo theo toàn bộ video và lịch sử).
const UNDO_MS = window.UNDO_MS || 8000;
function removeChannels(sel) {
  const names = sel.map((c) => c.username);
  names.forEach((n) => pendingDelete.add(n));
  table.clearSelection();
  lastJson = "";
  load();
  let undone = false;
  const label = names.length === 1 ? `@${sel[0].unique_id || sel[0].username}` : `${names.length} kênh`;
  toast(`Đã xóa ${label} cùng toàn bộ video`, "", {
    ms: UNDO_MS,
    action: {
      label: "Hoàn tác",
      fn: () => {
        undone = true;
        names.forEach((n) => pendingDelete.delete(n));
        lastJson = "";
        load();
      },
    },
  });
  setTimeout(async () => {
    if (undone) return;
    try {
      await api("/api/channels/delete", { usernames: names });
    } catch (e) {
      toast("Không xóa được: " + e.message, "err");
    } finally {
      names.forEach((n) => pendingDelete.delete(n));
      lastJson = "";
      load();
    }
  }, UNDO_MS + 200);
}

function prompt2(title, value, hint) {
  return new Promise((resolve) => {
    const d = $("#dlgPrompt");
    $("#promptTitle").textContent = title;
    $("#promptHint").textContent = hint || "";
    $("#promptInput").value = value || "";
    $("#promptOk").onclick = () => { d.close(); resolve($("#promptInput").value.trim()); };
    $("#promptCancel").onclick = () => { d.close(); resolve(null); };
    $("#promptInput").onkeydown = (e) => e.key === "Enter" && $("#promptOk").click();
    d.onclose = () => resolve(null);
    d.showModal();
    $("#promptInput").select();
  });
}

async function editGroup(sel) {
  const v = await prompt2(sel.length === 1 ? "Gắn nhóm cho kênh" : `Gắn nhóm cho ${sel.length} kênh`, sel[0].group_name, "Để trống để bỏ nhóm");
  if (v === null) return;
  await api("/api/channels/meta", { usernames: sel.map((c) => c.username), group_name: v });
  load();
}

async function editNote(sel) {
  const v = await prompt2(sel.length === 1 ? "Ghi chú" : `Ghi chú cho ${sel.length} kênh`, sel[0].note);
  if (v === null) return;
  await api("/api/channels/meta", { usernames: sel.map((c) => c.username), note: v });
  load();
}

function copyStats(sel) {
  const head = ["Username", "Tên kênh", "Follow", "Lượt thích", "Tổng view", "Số video", "View TB/video", "Tương tác %"];
  const lines = sel.map((c) => [c.unique_id || c.username, c.nickname || "", c.followers ?? "", c.likes ?? "", c.total_views ?? "", c.video_count ?? "", c.avg_views ?? "", c.er ?? ""].join("\t"));
  copyText([head.join("\t"), ...lines].join("\n"), `Đã sao chép số liệu ${sel.length} kênh`);
}

function exportExcel(sel) {
  const q = sel?.length ? "?usernames=" + encodeURIComponent(sel.map((c) => c.username).join(",")) : "";
  location.href = "/api/export/channels.xlsx" + q;
}

$("#search").addEventListener("input", applyFilter);
$("#groupFilter").addEventListener("change", applyFilter);
$("#btnRefreshAll").onclick = () => table.rows.length && refresh(table.view, QUICK);
$("#btnScan").onclick = () => scanChannels(table.getSelected().length ? table.getSelected() : table.view);
$("#btnExport").onclick = () => exportExcel(table.getSelected());
$("#btnColumns").onclick = (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  table.showColumnMenu(r.left, r.bottom + 4);
};
setCompactToggle($("#btnCompact"), () => table.render());

bindTableKeys(table, {
  Enter: (sel) => openUrls(sel.map(videosUrl)),
  Delete: removeChannels,
  F5: (sel) => refresh(sel, QUICK),
  copy: (sel) => copyText(sel.map((c) => c.unique_id || c.username).join("\n")),
  " ": (sel) => openDrawer(sel[0]),
});

// ---------------------------------------------------------------- cài đặt

const hourOptions = '<option value="">Tắt</option>' + Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
$("#setQuietStart").innerHTML = hourOptions;
$("#setQuietEnd").innerHTML = hourOptions;

function applyLook() {
  const theme = localStorage.getItem("theme") || "auto";
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.body.classList.toggle("dense", localStorage.getItem("dense") === "1");
}
applyLook();

$("#btnSettings").onclick = async () => {
  const s = await api("/api/settings");
  $("#setShowBrowser").checked = s.show_browser === "1";
  $("#setAuto").value = s.auto_refresh_minutes;
  $("#setAutoMode").value = s.auto_refresh_mode || "quick";
  $("#setQuietStart").value = s.quiet_start ?? "";
  $("#setQuietEnd").value = s.quiet_end ?? "";
  $("#setAlerts").checked = s.alerts_enabled !== "0";
  $("#setAlertPct").value = s.alert_follow_pct ?? "5";
  $("#setAlertVideo").checked = s.alert_new_video !== "0";
  $("#setTheme").value = localStorage.getItem("theme") || "auto";
  $("#setDense").checked = localStorage.getItem("dense") === "1";
  api("/api/backups").then((b) => {
    const n = b.backups.length;
    $("#backupInfo").textContent = n
      ? `Đã có ${n} bản sao lưu tự động, gần nhất ${new Date(b.backups[0].mtime * 1000).toLocaleString("vi-VN")}. Tool sao lưu mỗi ngày và trước khi nâng cấp cấu trúc dữ liệu (giữ 7 bản).`
      : "Tool tự sao lưu mỗi ngày và trước khi nâng cấp cấu trúc dữ liệu (giữ 7 bản).";
  }).catch(() => {});
  $("#dlgSettings").showModal();
};
$("#btnBackup").onclick = () => (location.href = "/api/export/backup");
$("#btnAbout").onclick = () => $("#dlgAbout").showModal();
$("#aboutClose").onclick = () => $("#dlgAbout").close();
$("#setCancel").onclick = () => $("#dlgSettings").close();
$("#btnShutdown").onclick = async () => {
  if (!confirm("Tắt tool? Việc quét đang chạy sẽ dừng. Mở lại bằng file ttwatch.exe.")) return;
  await api("/api/shutdown", {}).catch(() => {});
  $("#dlgSettings").close();
  toast("Đã tắt tool");
};
$("#setSave").onclick = async () => {
  localStorage.setItem("theme", $("#setTheme").value);
  localStorage.setItem("dense", $("#setDense").checked ? "1" : "0");
  applyLook();
  await api("/api/settings", {
    show_browser: $("#setShowBrowser").checked ? "1" : "0",
    auto_refresh_minutes: Math.max(0, parseInt($("#setAuto").value) || 0),
    auto_refresh_mode: $("#setAutoMode").value,
    quiet_start: $("#setQuietStart").value,
    quiet_end: $("#setQuietEnd").value,
    alerts_enabled: $("#setAlerts").checked ? "1" : "0",
    alert_follow_pct: String(Math.max(0, parseFloat($("#setAlertPct").value) || 0)),
    alert_new_video: $("#setAlertVideo").checked ? "1" : "0",
  });
  $("#dlgSettings").close();
  toast("Đã lưu cài đặt");
};

load();
loadSparks();
setInterval(load, 2000);
setInterval(loadSparks, 60000);
setInterval(() => table.render(), 60000); // làm mới "x phút trước"
