// ---------------------------------------------------------------- tiện ích

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("vi-VN");

let compactNumbers = localStorage.getItem("compact") === "1";

function fmtNum(n) {
  if (n === null || n === undefined || n === "") return '<span class="muted">–</span>';
  if (!compactNumbers || Math.abs(n) < 10000) return nf.format(n);
  const units = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
  for (const [v, u] of units) if (Math.abs(n) >= v) return (n / v).toFixed(Math.abs(n) >= v * 100 ? 0 : 1).replace(".", ",") + u;
  return nf.format(n);
}

function fmtDelta(d) {
  if (d === null || d === undefined || d === 0) return "";
  const cls = d > 0 ? "up" : "down";
  return ` <span class="delta ${cls}">${d > 0 ? "+" : "−"}${fmtNum(Math.abs(d))}</span>`;
}

function fmtDate(ts, withTime = false) {
  if (!ts) return '<span class="muted">–</span>';
  const d = new Date(ts * 1000);
  const p = (x) => String(x).padStart(2, "0");
  const s = `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
  return withTime ? `${s} ${p(d.getHours())}:${p(d.getMinutes())}` : s;
}

function fmtAgo(ts) {
  if (!ts) return '<span class="muted">–</span>';
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} ngày trước`;
  return fmtDate(ts);
}

function fmtDuration(s) {
  if (!s) return '<span class="muted">–</span>';
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function openUrls(urls) {
  if (!urls.length) return;
  if (urls.length === 1) window.open(urls[0], "_blank");
  else api("/api/open", { urls });
}

async function copyText(text, label = "Đã sao chép") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(label);
}

function toast(msg, type = "") {
  let box = $("#toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "toasts";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.classList.add("hide"), 3200);
  setTimeout(() => t.remove(), 3600);
}

// ---------------------------------------------------------------- menu chuột phải

const ContextMenu = {
  el: null,
  show(x, y, items) {
    this.hide();
    const m = document.createElement("div");
    m.className = "ctx-menu";
    for (const it of items) {
      if (it === "-") {
        m.appendChild(Object.assign(document.createElement("div"), { className: "ctx-sep" }));
        continue;
      }
      if (it.header) {
        m.appendChild(Object.assign(document.createElement("div"), { className: "ctx-header", textContent: it.header }));
        continue;
      }
      const b = document.createElement("button");
      b.className = "ctx-item" + (it.danger ? " danger" : "");
      b.disabled = !!it.disabled;
      b.innerHTML = `<span class="ctx-icon">${it.icon || ""}</span><span>${esc(it.label)}</span>${it.hint ? `<kbd>${esc(it.hint)}</kbd>` : ""}`;
      b.onclick = () => {
        this.hide();
        it.action();
      };
      m.appendChild(b);
    }
    document.body.appendChild(m);
    const r = m.getBoundingClientRect();
    m.style.left = Math.min(x, innerWidth - r.width - 6) + "px";
    m.style.top = Math.min(y, innerHeight - r.height - 6) + "px";
    this.el = m;
  },
  hide() {
    this.el?.remove();
    this.el = null;
  },
};
addEventListener("mousedown", (e) => ContextMenu.el && !ContextMenu.el.contains(e.target) && ContextMenu.hide());
addEventListener("keydown", (e) => e.key === "Escape" && ContextMenu.hide());
addEventListener("blur", () => ContextMenu.hide());
addEventListener("resize", () => ContextMenu.hide());

// ---------------------------------------------------------------- bảng dữ liệu

/**
 * columns: [{key, label, get(row) -> giá trị để sort, render(row) -> html, align, title, hidden, nosort}]
 */
class DataTable {
  constructor({ el, columns, rowKey, storageKey, onContextMenu, onOpen, onSelectionChange, rowClass }) {
    Object.assign(this, { el, columns, rowKey, storageKey, onContextMenu, onOpen, onSelectionChange, rowClass });
    this.rows = [];
    this.view = [];
    this.selected = new Set();
    this.anchor = null;
    this.filter = "";
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    this.sort = saved.sort || null;
    this.hiddenCols = new Set(saved.hidden || columns.filter((c) => c.hidden).map((c) => c.key));
    this.el.innerHTML = '<table class="grid"><thead></thead><tbody></tbody></table><div class="empty"></div>';
    this.thead = $("thead", el);
    this.tbody = $("tbody", el);
    this.emptyEl = $(".empty", el);
    this._bind();
  }

  save() {
    localStorage.setItem(this.storageKey, JSON.stringify({ sort: this.sort, hidden: [...this.hiddenCols] }));
  }

  visibleColumns() {
    return this.columns.filter((c) => !this.hiddenCols.has(c.key));
  }

  setRows(rows) {
    this.rows = rows;
    const keys = new Set(rows.map(this.rowKey));
    for (const k of [...this.selected]) if (!keys.has(k)) this.selected.delete(k);
    this.render();
  }

  setFilter(fn) {
    this.filterFn = fn;
    this.render();
  }

  render() {
    const cols = this.visibleColumns();
    let view = this.filterFn ? this.rows.filter(this.filterFn) : [...this.rows];
    if (this.sort) {
      const col = this.columns.find((c) => c.key === this.sort.key);
      if (col) {
        const get = col.get || ((r) => r[col.key]);
        const dir = this.sort.dir;
        view.sort((a, b) => {
          let x = get(a), y = get(b);
          const xe = x === null || x === undefined || x === "", ye = y === null || y === undefined || y === "";
          if (xe || ye) return xe && ye ? 0 : xe ? 1 : -1;
          if (typeof x === "string") return x.localeCompare(y, "vi") * dir;
          return (x - y) * dir;
        });
      }
    }
    this.view = view;
    this.thead.innerHTML =
      "<tr>" +
      cols
        .map((c) => {
          const s = this.sort?.key === c.key ? (this.sort.dir > 0 ? " ▲" : " ▼") : "";
          return `<th data-key="${c.key}" class="${c.align || ""} ${c.nosort ? "" : "sortable"}" title="${esc(c.title || "")}">${esc(c.label)}${s}</th>`;
        })
        .join("") +
      "</tr>";
    this.tbody.innerHTML = view
      .map((r, i) => {
        const k = this.rowKey(r);
        const cls = (this.selected.has(k) ? "sel " : "") + (this.rowClass ? this.rowClass(r) : "");
        return `<tr data-i="${i}" class="${cls}">` + cols.map((c) => `<td class="${c.align || ""} col-${c.key}">${c.render ? c.render(r, i) : esc(r[c.key])}</td>`).join("") + "</tr>";
      })
      .join("");
    this.emptyEl.style.display = view.length ? "none" : "block";
    this.emptyEl.innerHTML = this.rows.length ? "Không có kết quả phù hợp" : this.emptyText || "Chưa có dữ liệu";
    this.onSelectionChange?.(this.getSelected());
  }

  getSelected() {
    return this.view.filter((r) => this.selected.has(this.rowKey(r)));
  }

  _paintSelection() {
    for (const tr of this.tbody.rows) {
      const r = this.view[+tr.dataset.i];
      tr.classList.toggle("sel", this.selected.has(this.rowKey(r)));
    }
    this.onSelectionChange?.(this.getSelected());
  }

  selectRange(a, b, additive) {
    if (!additive) this.selected.clear();
    const [lo, hi] = a < b ? [a, b] : [b, a];
    for (let i = lo; i <= hi; i++) this.selected.add(this.rowKey(this.view[i]));
    this._paintSelection();
  }

  selectAll() {
    this.view.forEach((r) => this.selected.add(this.rowKey(r)));
    this._paintSelection();
  }

  clearSelection() {
    this.selected.clear();
    this._paintSelection();
  }

  _bind() {
    this.thead.addEventListener("click", (e) => {
      const th = e.target.closest("th.sortable");
      if (!th) return;
      const key = th.dataset.key;
      if (this.sort?.key !== key) this.sort = { key, dir: -1 };
      else if (this.sort.dir === -1) this.sort = { key, dir: 1 };
      else this.sort = null;
      this.save();
      this.render();
    });

    let dragStart = null;
    this.tbody.addEventListener("mousedown", (e) => {
      const tr = e.target.closest("tr");
      if (!tr || e.button !== 0 || e.target.closest("a, button, input")) return;
      const i = +tr.dataset.i;
      const k = this.rowKey(this.view[i]);
      if (e.shiftKey && this.anchor !== null) {
        this.selectRange(this.anchor, i, e.ctrlKey || e.metaKey);
      } else if (e.ctrlKey || e.metaKey) {
        this.selected.has(k) ? this.selected.delete(k) : this.selected.add(k);
        this.anchor = i;
        this._paintSelection();
      } else {
        this.anchor = i;
        dragStart = i;
        this.selected.clear();
        this.selected.add(k);
        this._paintSelection();
      }
      e.preventDefault();
    });
    this.tbody.addEventListener("mouseover", (e) => {
      if (dragStart === null) return;
      const tr = e.target.closest("tr");
      if (!tr) return;
      this.selectRange(dragStart, +tr.dataset.i, false);
    });
    addEventListener("mouseup", () => (dragStart = null));

    this.tbody.addEventListener("dblclick", (e) => {
      const tr = e.target.closest("tr");
      if (tr && !e.target.closest("a")) this.onOpen?.(this.view[+tr.dataset.i]);
    });

    this.tbody.addEventListener("contextmenu", (e) => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      e.preventDefault();
      const i = +tr.dataset.i;
      const k = this.rowKey(this.view[i]);
      if (!this.selected.has(k)) {
        this.selected.clear();
        this.selected.add(k);
        this.anchor = i;
        this._paintSelection();
      }
      this.onContextMenu?.(e, this.getSelected());
    });

    this.el.addEventListener("contextmenu", (e) => {
      if (!e.target.closest("tbody tr") && !e.target.closest("thead")) e.preventDefault();
    });
    this.thead.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      this.showColumnMenu(e.clientX, e.clientY);
    });
  }

  showColumnMenu(x, y) {
    ContextMenu.show(x, y, [
      { header: "Hiện / ẩn cột" },
      ...this.columns
        .filter((c) => !c.fixed)
        .map((c) => ({
          label: c.label || c.title,
          icon: this.hiddenCols.has(c.key) ? "" : "✓",
          action: () => {
            this.hiddenCols.has(c.key) ? this.hiddenCols.delete(c.key) : this.hiddenCols.add(c.key);
            this.save();
            this.render();
            this.showColumnMenu(x, y);
          },
        })),
    ]);
  }
}

// phím tắt chung cho bảng (không áp dụng khi đang gõ trong ô nhập)
function bindTableKeys(table, handlers) {
  addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select, dialog")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      table.selectAll();
    } else if (e.key === "Escape") table.clearSelection();
    else if (handlers[e.key]) {
      const sel = table.getSelected();
      if (sel.length) {
        e.preventDefault();
        handlers[e.key](sel);
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && handlers.copy) {
      const sel = table.getSelected();
      if (sel.length && !getSelection().toString()) handlers.copy(sel);
    }
  });
}

// ---------------------------------------------------------------- tùy chọn quét video

const SCAN_TYPES = [
  ["all", "Toàn bộ video"],
  ["limit", "Số video gần nhất"],
  ["days", "Số ngày gần nhất"],
  ["range", "Từ ngày … đến ngày"],
];

/** Gắn bộ chọn kiểu quét vào el. Trả về { job() -> job hoặc null nếu nhập sai, label() } */
function mountScanOptions(el, storageKey) {
  const today = new Date().toISOString().slice(0, 10);
  const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
  const s = { type: "all", limit: 50, days: 30, from: "", to: today, ...saved };
  el.classList.add("scan-opts");
  el.innerHTML =
    `<select data-k="type">${SCAN_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>` +
    `<span data-show="limit"><input type="number" data-k="limit" min="1" step="10"> video</span>` +
    `<span data-show="days"><input type="number" data-k="days" min="1" step="1"> ngày</span>` +
    `<span data-show="range"><input type="date" data-k="from"> → <input type="date" data-k="to"></span>`;
  const inputs = [...el.querySelectorAll("[data-k]")];
  inputs.forEach((i) => (i.value = s[i.dataset.k] ?? ""));
  const sync = () => {
    const type = el.querySelector('[data-k="type"]').value;
    el.querySelectorAll("[data-show]").forEach((x) => (x.style.display = x.dataset.show === type ? "" : "none"));
    localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(inputs.map((i) => [i.dataset.k, i.value]))));
  };
  inputs.forEach((i) => i.addEventListener("input", sync));
  sync();
  const val = (k) => el.querySelector(`[data-k="${k}"]`).value;
  return {
    job() {
      const type = val("type");
      if (type === "limit") {
        const n = parseInt(val("limit"));
        return n > 0 ? { mode: "scan", limit: n } : (toast("Hãy nhập số video lớn hơn 0", "err"), null);
      }
      if (type === "days") {
        const n = parseInt(val("days"));
        return n > 0 ? { mode: "scan", days: n } : (toast("Hãy nhập số ngày lớn hơn 0", "err"), null);
      }
      if (type === "range") {
        const from = val("from"), to = val("to");
        if (!from && !to) return toast("Hãy chọn ít nhất một ngày", "err"), null;
        return {
          mode: "scan",
          since: from ? Math.floor(new Date(from + "T00:00:00").getTime() / 1000) : 0,
          until: to ? Math.floor(new Date(to + "T23:59:59").getTime() / 1000) : 0,
        };
      }
      return { mode: "scan" };
    },
    label() {
      const type = val("type");
      if (type === "limit") return `${val("limit")} video gần nhất`;
      if (type === "days") return `video trong ${val("days")} ngày qua`;
      if (type === "range") return `video ${val("from") ? "từ " + val("from").split("-").reverse().join("/") : ""} ${val("to") ? "đến " + val("to").split("-").reverse().join("/") : ""}`.trim();
      return "toàn bộ video";
    },
  };
}

/** Hộp thoại chọn kiểu quét. Trả về job hoặc null nếu hủy. */
function scanDialog(title) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.innerHTML = `<h3>${esc(title)}</h3>
      <div class="field"><label>Quét video nào?</label><div class="opts"></div>
      <small>Video được ghim trên kênh cũng được xét theo ngày đăng.</small></div>
      <div class="dlg-actions"><button class="btn cancel">Hủy</button><button class="btn primary ok">Bắt đầu quét</button></div>`;
    document.body.appendChild(d);
    const opts = mountScanOptions($(".opts", d), "scan-dialog");
    let result = null;
    $(".cancel", d).onclick = () => d.close();
    $(".ok", d).onclick = () => {
      result = opts.job();
      if (result) d.close();
    };
    d.addEventListener("keydown", (e) => e.key === "Enter" && $(".ok", d).click());
    d.onclose = () => {
      d.remove();
      resolve(result);
    };
    d.showModal();
  });
}

function setCompactToggle(btn, rerender) {
  const sync = () => btn.classList.toggle("on", compactNumbers);
  sync();
  btn.onclick = () => {
    compactNumbers = !compactNumbers;
    localStorage.setItem("compact", compactNumbers ? "1" : "0");
    sync();
    rerender();
  };
}
