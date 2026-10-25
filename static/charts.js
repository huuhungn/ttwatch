// Plain SVG charts, no library dependency. Colors come from the CSS variables --c1..--c6.

const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

  // Plain-text numbers (1,2M) for axes and tooltips.
  function short(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "–";
    const a = Math.abs(n);
    for (const [v, u] of [[1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
      if (a >= v) {
        let t = (n / v).toFixed(a >= v * 100 ? 0 : a >= v * 10 ? 1 : 2);
        if (t.includes(".")) t = t.replace(/\.?0+$/, ""); // strip only trailing zeros after the decimal point (50 stays as is)
        return t.replace(".", ",") + u;
      }
    }
    return String(Math.round(n));
  }

  function full(n) {
    return n === null || n === undefined ? "–" : new Intl.NumberFormat("vi-VN").format(Math.round(n));
  }

  // "Nice" axis step: 1, 2, 5 × 10^k.
  function niceStep(range, ticks) {
    const raw = range / Math.max(1, ticks);
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const norm = raw / mag;
    return (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  }

  function axisY(min, max) {
    if (min === max) {
      const pad = Math.abs(min) * 0.05 || 1;
      min -= pad;
      max += pad;
    }
    const step = niceStep(max - min, 4);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
    return { lo, hi, ticks };
  }

  function dayLabel(ts, spanDays) {
    const d = new Date(ts * 1000);
    const p = (x) => String(x).padStart(2, "0");
    return spanDays <= 2 ? `${p(d.getHours())}:${p(d.getMinutes())}` : `${p(d.getDate())}/${p(d.getMonth() + 1)}`;
  }

  /**
   * series: [{ name, points: [[ts, value], ...], color? }]
   * opts: { height, fmt(value) -> text, axisFmt(tick) -> text, empty }
   * Redraws on resize. Returns a dispose function.
   */
  function line(el, series, opts = {}) {
    const height = opts.height || 220;
    const fmt = opts.fmt || full;
    const axisFmt = opts.axisFmt || short;
    el.classList.add("chart");
    el.style.position = "relative";

    function draw() {
      const W = Math.max(280, el.clientWidth || 600);
      const all = series.flatMap((s) => s.points.filter((p) => p[1] !== null && p[1] !== undefined));
      if (!all.length) {
        el.innerHTML = `<div class="chart-empty">${esc(opts.empty || "Chưa có đủ dữ liệu để vẽ biểu đồ – cần ít nhất hai lần cập nhật.")}</div>`;
        return;
      }
      const L = 54, R = 14, T = 12, B = 26;
      const xs = all.map((p) => p[0]);
      let x0 = Math.min(...xs), x1 = Math.max(...xs);
      if (x0 === x1) { x0 -= 3600; x1 += 3600; }
      const ay = axisY(Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1])));
      const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
      const Y = (v) => T + (1 - (v - ay.lo) / (ay.hi - ay.lo)) * (height - T - B);
      const spanDays = (x1 - x0) / 86400;

      let g = "";
      for (const t of ay.ticks) {
        g += `<line class="grid-l" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/>`;
        g += `<text class="axis" x="${L - 8}" y="${Y(t) + 4}" text-anchor="end">${axisFmt(t)}</text>`;
      }
      const nx = Math.max(2, Math.min(6, Math.floor((W - L - R) / 90)));
      for (let i = 0; i <= nx; i++) {
        const t = x0 + ((x1 - x0) * i) / nx;
        g += `<text class="axis" x="${X(t)}" y="${height - 7}" text-anchor="${i === 0 ? "start" : i === nx ? "end" : "middle"}">${dayLabel(t, spanDays)}</text>`;
      }
      series.forEach((s, i) => {
        const pts = s.points.filter((p) => p[1] !== null && p[1] !== undefined);
        if (!pts.length) return;
        const color = s.color || PALETTE[i % PALETTE.length];
        const d = pts.map((p, j) => `${j ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
        if (series.length === 1 && pts.length > 1) {
          g += `<path class="area" d="${d}L${X(pts[pts.length - 1][0]).toFixed(1)},${Y(ay.lo)}L${X(pts[0][0]).toFixed(1)},${Y(ay.lo)}Z" fill="${color}"/>`;
        }
        g += `<path class="ln" d="${d}" stroke="${color}" fill="none"/>`;
        if (pts.length <= 40) g += pts.map((p) => `<circle class="pt" cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="2.6" fill="${color}"/>`).join("");
      });
      el.innerHTML =
        `<svg width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" role="img" aria-label="${esc(opts.label || "Biểu đồ")}">${g}` +
        `<line class="guide" y1="${T}" y2="${height - B}" x1="-10" x2="-10"/></svg><div class="chart-tip" hidden></div>`;

      const svg = el.firstElementChild;
      const tip = el.lastElementChild;
      const guide = svg.querySelector(".guide");
      const move = (e) => {
        const r = svg.getBoundingClientRect();
        const t = x0 + ((e.clientX - r.left - L) / (W - L - R)) * (x1 - x0);
        const rows = [];
        let at = null;
        series.forEach((s, i) => {
          let best = null;
          for (const p of s.points) if (p[1] != null && (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t))) best = p;
          if (best) {
            rows.push({ name: s.name, value: best[1], ts: best[0], color: s.color || PALETTE[i % PALETTE.length] });
            if (!at || Math.abs(best[0] - t) < Math.abs(at - t)) at = best[0];
          }
        });
        if (at === null) return;
        guide.setAttribute("x1", X(at));
        guide.setAttribute("x2", X(at));
        const d = new Date(at * 1000);
        const p2 = (x) => String(x).padStart(2, "0");
        const when = `${p2(d.getDate())}/${p2(d.getMonth() + 1)}/${d.getFullYear()} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
        tip.innerHTML = `<div class="tip-time">${when}</div>` +
          rows.map((r) => `<div><i style="background:${r.color}"></i>${r.name ? esc(r.name) + ": " : ""}<b>${fmt(r.value)}</b></div>`).join("");
        tip.hidden = false;
        const left = Math.min(Math.max(X(at) + 12, 0), W - tip.offsetWidth - 4);
        tip.style.left = left + "px";
        tip.style.top = "8px";
      };
      svg.addEventListener("mousemove", move);
      svg.addEventListener("mouseleave", () => {
        tip.hidden = true;
        guide.setAttribute("x1", -10);
        guide.setAttribute("x2", -10);
      });
    }

    draw();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => draw()) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }

  /** Small trend line for a table cell. values: [number...]. Returns an SVG string. */
  function spark(values, { w = 84, h = 24 } = {}) {
    const v = (values || []).filter((x) => x !== null && x !== undefined);
    if (v.length < 2) return '<span class="muted">–</span>';
    const lo = Math.min(...v), hi = Math.max(...v);
    const span = hi - lo || 1;
    const pts = v.map((x, i) => `${((i / (v.length - 1)) * (w - 4) + 2).toFixed(1)},${(h - 3 - ((x - lo) / span) * (h - 6)).toFixed(1)}`);
    const up = v[v.length - 1] >= v[0];
    const flat = hi === lo;
    const cls = flat ? "flat" : up ? "up" : "down";
    return `<svg class="spark ${cls}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts.join(" ")}" fill="none"/></svg>`;
  }

  /** Horizontal bars: items [{label, value}]. */
  function bars(items, { fmt = full } = {}) {
    const max = Math.max(1, ...items.map((i) => i.value));
    return `<div class="bars">${items
      .map((i) => `<div class="bar-row"><span class="bar-l">${esc(i.label)}</span><span class="bar-t"><span class="bar-f" style="width:${(i.value / max) * 100}%"></span></span><span class="bar-v">${fmt(i.value)}</span></div>`)
      .join("")}</div>`;
  }

  /** Small vertical bars: items [{label, value}] (e.g. posts per week). */
  function columns(items, { height = 70 } = {}) {
    const max = Math.max(1, ...items.map((i) => i.value));
    return `<div class="cols" style="height:${height}px">${items
      .map((i) => `<div class="col" title="${esc(i.label)}: ${i.value}"><span style="height:${Math.max(i.value ? 4 : 1, (i.value / max) * (height - 16))}px"></span><em>${i.value || ""}</em></div>`)
      .join("")}</div>`;
  }

  /** 7×24 heatmap: matrix[weekday][hour] = {count, avg_views}. */
  function heatmap(matrix) {
    const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
    const max = Math.max(1, ...matrix.flat().map((c) => c.avg_views));
    let html = '<div class="heat"><div class="heat-h"></div>';
    for (let h = 0; h < 24; h++) html += `<div class="heat-h">${h % 3 === 0 ? h : ""}</div>`;
    matrix.forEach((row, d) => {
      html += `<div class="heat-d">${days[d]}</div>`;
      row.forEach((c, h) => {
        const a = c.count ? 0.18 + 0.82 * (c.avg_views / max) : 0;
        html += `<div class="heat-c${c.count ? "" : " none"}" style="--a:${a.toFixed(2)}" title="${days[d]} ${h}h – ${c.count} video, TB ${full(c.avg_views)} view"></div>`;
      });
    });
    return html + "</div>";
  }

  return { line, spark, bars, columns, heatmap, short, full, PALETTE };
})();
