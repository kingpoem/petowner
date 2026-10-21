"use strict";

(() => {
  const ready = (fn) =>
    document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", fn) : fn();

  ready(() => {
    document.querySelectorAll(".toast").forEach((el) => new bootstrap.Toast(el).show());

    // 锚点滚动：布局/图片稳定后再定位，避免首次落到错误位置
    const settleHashScroll = (id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const go = () => el.scrollIntoView({ behavior: "auto", block: "start" });
      go();
      requestAnimationFrame(go);
      window.setTimeout(go, 120);
      window.setTimeout(go, 400);
      if (document.readyState !== "complete") {
        window.addEventListener(
          "load",
          () => {
            go();
            window.setTimeout(go, 200);
          },
          { once: true },
        );
      }
    };
    const hashId = () =>
      location.hash.length > 1 ? decodeURIComponent(location.hash.slice(1)) : "";
    if (hashId()) settleHashScroll(hashId());
    document.addEventListener("click", (e) => {
      const link = e.target.closest("a[href]");
      if (!link) return;
      let url;
      try {
        url = new URL(link.href, location.href);
      } catch {
        return;
      }
      if (url.origin !== location.origin || url.pathname !== location.pathname || !url.hash) return;
      const id = decodeURIComponent(url.hash.slice(1));
      if (!document.getElementById(id)) return;
      e.preventDefault();
      if (location.hash !== url.hash) history.pushState(null, "", url.hash);
      settleHashScroll(id);
    });

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

    // 实时报价：房间/日期/加购变化时局部刷新费用明细
    document.querySelectorAll("form[data-quote-url]").forEach((form) => {
      const target = document.querySelector(form.dataset.quoteTarget);
      const fields = ["pet", "room", "check_in", "check_out"];
      let controller;
      let timer;

      const syncAddons = () => {
        const pet = form.elements.pet;
        const selected = pet?.selectedOptions?.[0];
        const species = selected?.dataset?.species || "";
        form.querySelectorAll(".addon-option[data-species]").forEach((row) => {
          const fit = !species || row.dataset.species === "any" || row.dataset.species === species;
          row.hidden = !fit;
          if (!fit) {
            const box = row.querySelector('input[type="checkbox"]');
            if (box?.checked) box.checked = false;
          }
        });
      };

      const refresh = async () => {
        const params = new URLSearchParams();
        fields.forEach((name) => {
          const value = form.elements[name]?.value;
          if (value) params.set(name, value);
        });
        form.querySelectorAll('input[name="addons"]:checked').forEach((el) => {
          if (!el.closest(".addon-option")?.hidden) params.append("addons", el.value);
        });
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
      form.elements.pet?.addEventListener("change", () => {
        syncAddons();
        schedule();
      });
      form.addEventListener("change", (event) => {
        if (event.target.name === "addons") schedule();
      });
      syncAddons();
    });
  });
})();
