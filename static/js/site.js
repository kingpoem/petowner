"use strict";

(() => {
  const ready = (fn) =>
    document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", fn) : fn();

  const navOffset = () => (document.querySelector(".site-nav")?.offsetHeight ?? 0) + 12;

  // 粘性顶栏会把平滑滚动提前打断，第一次点击会停在护理服务上面的房间卡片。
  // 滚动结束后再对齐一次，图片加载造成高度变化时也补一次。
  const alignHash = () => {
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const target = id && document.getElementById(id);
    if (!target) return;
    const anchor = target.querySelector("h1, h2") || target;
    const delta = anchor.getBoundingClientRect().top - navOffset();
    if (Math.abs(delta) > 8) window.scrollTo({ top: window.scrollY + delta, behavior: "auto" });
  };

  let alignUntil = 0;
  const watchHash = () => {
    alignUntil = performance.now() + 1500;
    alignHash();
    requestAnimationFrame(alignHash);
    setTimeout(alignHash, 60);
    setTimeout(alignHash, 300);
  };

  ready(() => {
    document.querySelectorAll(".toast").forEach((el) => new bootstrap.Toast(el).show());

    document.addEventListener("click", (event) => {
      const link = event.target.closest?.("a[href]");
      if (!link || link.target === "_blank") return;
      let url;
      try {
        url = new URL(link.href, location.href);
      } catch {
        return;
      }
      if (url.origin !== location.origin || url.pathname !== location.pathname || !url.hash) return;
      if (!document.getElementById(decodeURIComponent(url.hash.slice(1)))) return;
      event.preventDefault();
      if (location.hash !== url.hash) history.pushState(null, "", url.hash);
      watchHash();
    });

    document.querySelectorAll("img").forEach((img) => {
      if (!img.complete) {
        img.addEventListener("load", () => {
          if (performance.now() < alignUntil) alignHash();
        });
      }
    });

    if (location.hash) {
      if (document.readyState === "complete") watchHash();
      else window.addEventListener("load", watchHash);
    }

    // 危险操作二次确认：<form data-confirm="确定…？">
    document.addEventListener("submit", (e) => {
      const message = e.target.dataset?.confirm;
      if (message && !window.confirm(message)) e.preventDefault();
    });

    // 图片选择后即时预览：<input type="file" data-preview="#imgId">
    document.querySelectorAll("input[type=file][data-preview]").forEach((input) => {
      input.addEventListener("change", () => {
        const file = input.files[0];
        const target = document.querySelector(input.dataset.preview);
        if (file && target) {
          target.src = URL.createObjectURL(file);
          target.hidden = false;
        }
      });
    });

    // 快捷短语：<button data-fill-target="#textarea" data-fill="早餐">，追加到输入框
    document.querySelectorAll("[data-fill-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = document.querySelector(btn.dataset.fillTarget);
        if (!target) return;
        const current = target.value.trim();
        target.value = current ? `${current.replace(/[，。；,;]$/, "")}，${btn.dataset.fill}` : btn.dataset.fill;
        target.focus();
      });
    });

    // 图片灯箱：<a href="大图" data-lightbox="分组" data-caption="说明">，支持左右切换与键盘操作
    const lightboxLinks = [...document.querySelectorAll("a[data-lightbox]")];
    if (lightboxLinks.length) {
      const modalEl = document.createElement("div");
      modalEl.className = "modal fade lightbox";
      modalEl.tabIndex = -1;
      modalEl.setAttribute("aria-label", "图片预览");
      modalEl.innerHTML = `
        <div class="modal-dialog modal-dialog-centered modal-xl">
          <div class="modal-content">
            <button type="button" class="btn-close btn-close-white lightbox-close" data-bs-dismiss="modal" aria-label="关闭"></button>
            <button type="button" class="lightbox-nav prev" aria-label="上一张"><i class="bi bi-chevron-left"></i></button>
            <img class="lightbox-img" alt="">
            <button type="button" class="lightbox-nav next" aria-label="下一张"><i class="bi bi-chevron-right"></i></button>
            <div class="lightbox-caption"></div>
          </div>
        </div>`;
      document.body.appendChild(modalEl);
      const modal = new bootstrap.Modal(modalEl);
      const img = modalEl.querySelector(".lightbox-img");
      const caption = modalEl.querySelector(".lightbox-caption");
      let group = [];
      let index = 0;
      const show = (i) => {
        index = (i + group.length) % group.length;
        const link = group[index];
        img.src = link.href;
        img.alt = link.dataset.caption || "";
        caption.textContent = `${link.dataset.caption || ""}${group.length > 1 ? `（${index + 1}/${group.length}）` : ""}`;
        modalEl.querySelectorAll(".lightbox-nav").forEach((b) => (b.hidden = group.length < 2));
      };
      lightboxLinks.forEach((link) => {
        link.addEventListener("click", (e) => {
          e.preventDefault();
          group = lightboxLinks.filter((l) => l.dataset.lightbox === link.dataset.lightbox);
          show(group.indexOf(link));
          modal.show();
        });
      });
      modalEl.querySelector(".prev").addEventListener("click", () => show(index - 1));
      modalEl.querySelector(".next").addEventListener("click", () => show(index + 1));
      modalEl.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") show(index - 1);
        if (e.key === "ArrowRight") show(index + 1);
      });
      let touchX = null;
      img.addEventListener("touchstart", (e) => (touchX = e.touches[0].clientX), { passive: true });
      img.addEventListener("touchend", (e) => {
        if (touchX === null) return;
        const dx = e.changedTouches[0].clientX - touchX;
        if (Math.abs(dx) > 40) show(index + (dx < 0 ? 1 : -1));
        touchX = null;
      });
    }

    // 实时报价：房间/日期/优惠码/积分变化时局部刷新费用明细
    document.querySelectorAll("form[data-quote-url]").forEach((form) => {
      const target = document.querySelector(form.dataset.quoteTarget);
      const fields = ["pet", "room", "check_in", "check_out", "coupon_code", "redeem_points"];
      let controller;
      let timer;
      const refresh = async () => {
        const params = new URLSearchParams();
        fields.forEach((name) => {
          const value = form.elements[name]?.value;
          if (value) params.set(name, value);
        });
        if (form.elements.use_member?.checked) params.set("use_member", "on");
        form.querySelectorAll('input[name="addons"]:checked').forEach((el) => params.append("addons", el.value));
        if (form.dataset.order) params.set("order", form.dataset.order);
        controller?.abort();
        controller = new AbortController();
        target.classList.add("is-loading");
        try {
          const resp = await fetch(`${form.dataset.quoteUrl}?${params}`, {
            signal: controller.signal,
            headers: { "X-Requested-With": "fetch" },
          });
          if (resp.ok) target.innerHTML = await resp.text();
        } catch (err) {
          if (err.name !== "AbortError") console.error(err);
        } finally {
          target.classList.remove("is-loading");
        }
      };
      const schedule = () => {
        clearTimeout(timer);
        timer = setTimeout(refresh, 220);
      };
      fields.forEach((name) => {
        const el = form.elements[name];
        if (!el) return;
        el.addEventListener("change", schedule);
        el.addEventListener("input", schedule);
      });
      form.addEventListener("change", (event) => {
        if (event.target.name === "addons" || event.target.name === "use_member") schedule();
      });
    });

    // 日课折叠：拖动钟点，房间改用那个时刻之前最近的一条护理。
    document.querySelectorAll("[data-breath-replay]").forEach((root) => {
      const node = document.getElementById(root.dataset.breathReplay);
      const slider = root.querySelector('input[type="range"]');
      const clock = root.querySelector("[data-breath-clock]");
      if (!node || !slider || !clock) return;
      const data = JSON.parse(node.textContent);
      const paint = () => {
        const hour = String(slider.value);
        clock.textContent = `${hour.padStart(2, "0")}:00`;
        const frame = data.frames[hour] || {};
        root.querySelectorAll(".kennel.live").forEach((room) => {
          const state = frame[room.dataset.room];
          const caption = room.querySelector(".kennel-caption");
          if (!state) {
            room.style.setProperty("--breath", `${data.rest}s`);
            room.classList.remove("alert");
            if (caption) caption.textContent = "安稳";
            return;
          }
          room.style.setProperty("--breath", `${state.breath}s`);
          room.classList.toggle("alert", Boolean(state.alert));
          if (caption) caption.textContent = state.caption;
        });
      };
      slider.addEventListener("input", paint);
      paint();
    });
  });
})();
