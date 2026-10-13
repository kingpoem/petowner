"use strict";

// 中文日期选择器：渐进增强 <input type="date">，脚本未加载时回退为浏览器原生控件。
// 同一表单内成对的日期字段自动联动为区间（见 RANGES），选择开始日期后自动打开结束日期。
(() => {
  const RANGES = [
    {
      names: ["check_in", "check_out"],
      futureOnly: true,
      gap: 1,
      verb: "入住",
      startHint: "请选择入住日期",
      endHint: "请选择离店日期",
      count: (n) => `共 <b>${n}</b> 晚`,
    },
    {
      names: ["start", "end"],
      futureOnly: false,
      gap: 0,
      verb: "起",
      startHint: "请选择开始日期",
      endHint: "请选择结束日期",
      count: (n) => `共 <b>${n + 1}</b> 天`,
    },
  ];
  const chevron = (d) =>
    `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
  const DAY_MS = 86400000;
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const monthStart = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const same = (a, b) => Boolean(a && b) && a.getTime() === b.getTime();
  const nights = (a, b) => Math.round((b - a) / DAY_MS);
  const today = () => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  };
  const parse = (value) => {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec((value || "").trim());
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return d.getMonth() === +m[2] - 1 ? d : null;
  };
  const weekday = (d) => `周${WEEKDAYS[(d.getDay() + 6) % 7]}`;

  let openPicker = null;

  class DatePicker {
    constructor(input, { role = null, partner = null, rule = null } = {}) {
      this.input = input;
      this.role = role;
      this.partner = partner;
      this.rule = rule;
      this.staticMin = parse(input.min);
      this.staticMax = parse(input.max);
      input.type = "text";
      input.autocomplete = "off";
      input.inputMode = "none";
      input.placeholder ||= "年-月-日";
      input.classList.add("dp-input");
      input.setAttribute("aria-haspopup", "dialog");

      this.pop = document.createElement("div");
      this.pop.className = "dp";
      this.pop.hidden = true;
      this.pop.setAttribute("role", "dialog");
      this.pop.setAttribute("aria-label", `选择${input.labels?.[0]?.textContent.replace("*", "").trim() || "日期"}`);
      document.body.appendChild(this.pop);

      input.addEventListener("focus", () => this.quiet || this.open());
      input.addEventListener("click", () => this.open());
      input.addEventListener("input", () => {
        const d = parse(input.value);
        if (d) {
          this.cursor = d;
          this.view = monthStart(d);
          this.render();
        }
      });
      input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" || (e.key === "Enter" && this.pop.hidden)) {
          e.preventDefault();
          this.open();
          this.focusCursor();
        } else if (e.key === "Escape") {
          this.close();
        }
      });
      this.pop.addEventListener("mousedown", (e) => e.preventDefault());
      this.pop.addEventListener("click", (e) => this.onClick(e));
      this.pop.addEventListener("keydown", (e) => this.onKey(e));
      this.pop.addEventListener("mouseover", (e) => this.preview(e.target.closest(".dp-day")));
      this.pop.addEventListener("mouseleave", () => this.preview(null));
    }

    get value() {
      return parse(this.input.value);
    }

    min() {
      const bounds = [this.staticMin];
      if (this.rule?.futureOnly) bounds.push(today());
      if (this.role === "end" && this.partner.value) bounds.push(addDays(this.partner.value, this.rule.gap));
      return bounds.filter(Boolean).reduce((a, b) => (b > a ? b : a), null);
    }

    range() {
      if (!this.role) return [null, null];
      return this.role === "start" ? [this.value, this.partner.value] : [this.partner.value, this.value];
    }

    disabled(d) {
      const min = this.min();
      return (min && d < min) || (this.staticMax && d > this.staticMax);
    }

    open() {
      if (!this.pop.hidden) return;
      openPicker?.close();
      openPicker = this;
      const base = this.value || this.min() || today();
      this.cursor = this.disabled(base) ? this.min() || this.staticMax : base;
      this.view = monthStart(this.cursor);
      this.render();
      this.pop.hidden = false;
      this.input.setAttribute("aria-expanded", "true");
      this.place();
    }

    close() {
      if (this.pop.hidden) return;
      this.pop.hidden = true;
      this.input.setAttribute("aria-expanded", "false");
      if (openPicker === this) openPicker = null;
    }

    place() {
      const rect = this.input.getBoundingClientRect();
      const width = this.pop.offsetWidth;
      const left = Math.max(8, Math.min(rect.left, document.documentElement.clientWidth - width - 8));
      const below = rect.bottom + this.pop.offsetHeight + 8 <= window.innerHeight || rect.top < this.pop.offsetHeight;
      const top = below ? rect.bottom + 6 : rect.top - this.pop.offsetHeight - 6;
      this.pop.style.left = `${left + window.scrollX}px`;
      this.pop.style.top = `${top + window.scrollY}px`;
    }

    hint(hovered = null) {
      const [start, end] = this.range();
      const rule = this.rule;
      const valid = (a, b) => Boolean(a && b) && nights(a, b) >= rule.gap;
      if (this.role === "end" && start) {
        const until = hovered || end;
        return valid(start, until)
          ? `${start.getMonth() + 1}月${start.getDate()}日${rule.verb} · ${rule.count(nights(start, until))}`
          : rule.endHint;
      }
      if (this.role === "start") return valid(start, end) ? rule.count(nights(start, end)) : rule.startHint;
      return this.value ? `${iso(this.value)} ${weekday(this.value)}` : "";
    }

    render() {
      const { view, cursor } = this;
      const selected = this.value;
      const [start, end] = this.range();
      const now = today();
      const first = addDays(view, -((view.getDay() + 6) % 7));
      const prevDisabled = this.min() && monthStart(this.min()) >= view;
      const nextDisabled = this.staticMax && monthStart(this.staticMax) <= view;
      const days = Array.from({ length: 42 }, (_, i) => {
        const d = addDays(first, i);
        const cls = ["dp-day"];
        if (d.getMonth() !== view.getMonth()) cls.push("other");
        if (same(d, now)) cls.push("today");
        if (same(d, selected)) cls.push("selected");
        if (start && end && d > start && d < end) cls.push("in-range");
        if (this.role && same(d, start)) cls.push("range-start");
        if (this.role && same(d, end)) cls.push("range-end");
        const label = `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${weekday(d)}`;
        return `<button type="button" class="${cls.join(" ")}" data-date="${iso(d)}" tabindex="${same(d, cursor) ? 0 : -1}"
          aria-label="${label}"${same(d, selected) ? ' aria-pressed="true"' : ""}${this.disabled(d) ? " disabled" : ""}>${d.getDate()}</button>`;
      }).join("");
      const clearable = !this.input.required && this.input.value;
      this.pop.innerHTML = `
        <div class="dp-head">
          <button type="button" class="dp-nav" data-step="-1" aria-label="上个月"${prevDisabled ? " disabled" : ""}>${chevron("M10 3 5 8l5 5")}</button>
          <strong aria-live="polite">${view.getFullYear()} 年 ${view.getMonth() + 1} 月</strong>
          <button type="button" class="dp-nav" data-step="1" aria-label="下个月"${nextDisabled ? " disabled" : ""}>${chevron("m6 3 5 5-5 5")}</button>
        </div>
        <div class="dp-grid">${WEEKDAYS.map((w, i) => `<span class="dp-wd${i > 4 ? " weekend" : ""}">${w}</span>`).join("")}${days}</div>
        <div class="dp-foot">
          <span class="dp-hint">${this.hint()}</span>
          ${clearable ? '<button type="button" class="dp-link" data-action="clear">清除</button>' : ""}
          ${this.disabled(now) ? "" : '<button type="button" class="dp-link" data-action="today">今天</button>'}
        </div>`;
    }

    refocus() {
      this.quiet = true;
      this.input.focus({ preventScroll: true });
      this.quiet = false;
    }

    focusCursor() {
      this.pop.querySelector(`[data-date="${iso(this.cursor)}"]`)?.focus();
    }

    moveCursor(d) {
      if (this.disabled(d)) return;
      this.cursor = d;
      if (monthStart(d).getTime() !== this.view.getTime()) {
        this.view = monthStart(d);
        this.render();
      } else {
        this.pop.querySelectorAll(".dp-day").forEach((b) => (b.tabIndex = b.dataset.date === iso(d) ? 0 : -1));
      }
      this.focusCursor();
    }

    preview(button) {
      if (this.role !== "end") return;
      const [start] = this.range();
      const hovered = button && !button.disabled ? parse(button.dataset.date) : null;
      const until = hovered || this.value;
      this.pop.querySelectorAll(".dp-day").forEach((b) => {
        const d = parse(b.dataset.date);
        b.classList.toggle("in-range", Boolean(start && until && d > start && d < until));
        b.classList.toggle("range-end", same(d, until));
        b.classList.toggle("selected", same(d, until));
      });
      const hint = this.pop.querySelector(".dp-hint");
      if (hint) hint.innerHTML = this.hint(hovered);
    }

    select(d) {
      this.input.value = d ? iso(d) : "";
      const changed = [this.input];
      if (this.role === "start" && d) {
        const end = this.partner.value;
        if (!end || nights(d, end) < this.rule.gap) {
          this.partner.input.value = iso(addDays(d, this.rule.gap));
          changed.push(this.partner.input);
        }
      }
      this.close();
      changed.forEach((el) => {
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      });
      if (this.role === "start" && d) {
        this.partner.refocus();
        this.partner.open();
      } else {
        this.refocus();
      }
    }

    onClick(e) {
      const day = e.target.closest(".dp-day");
      if (day && !day.disabled) return this.select(parse(day.dataset.date));
      const nav = e.target.closest(".dp-nav");
      if (nav) {
        this.view = new Date(this.view.getFullYear(), this.view.getMonth() + +nav.dataset.step, 1);
        this.render();
        return;
      }
      const action = e.target.closest("[data-action]")?.dataset.action;
      if (action === "today") this.select(today());
      if (action === "clear") this.select(null);
    }

    onKey(e) {
      const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      if (e.key in steps) {
        e.preventDefault();
        this.moveCursor(addDays(this.cursor, steps[e.key]));
      } else if (e.key === "PageUp" || e.key === "PageDown") {
        e.preventDefault();
        const shift = e.key === "PageUp" ? -1 : 1;
        const d = new Date(this.cursor.getFullYear(), this.cursor.getMonth() + shift, this.cursor.getDate());
        this.moveCursor(this.disabled(d) ? this.min() : d);
      } else if (e.key === "Escape") {
        e.preventDefault();
        this.close();
        this.refocus();
      }
    }
  }

  const init = () => {
    const pickers = new Map();
    document.querySelectorAll("form").forEach((form) => {
      RANGES.forEach((rule) => {
        const [start, end] = rule.names.map((name) => form.elements[name]);
        if (start?.type === "date" && end?.type === "date") {
          const a = new DatePicker(start, { role: "start", rule });
          const b = new DatePicker(end, { role: "end", partner: a, rule });
          a.partner = b;
          pickers.set(start, a).set(end, b);
        }
      });
    });
    document.querySelectorAll('input[type="date"]').forEach((input) => pickers.set(input, new DatePicker(input)));

    document.addEventListener("mousedown", (e) => {
      if (openPicker && e.target !== openPicker.input && !openPicker.pop.contains(e.target)) openPicker.close();
    });
    document.addEventListener("focusin", (e) => {
      if (openPicker && e.target !== openPicker.input && !openPicker.pop.contains(e.target)) openPicker.close();
    });
    window.addEventListener("resize", () => openPicker?.place());
  };

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
