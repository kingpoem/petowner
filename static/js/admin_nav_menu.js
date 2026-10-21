/** 顶栏「首页」紧凑下拉 */
(function () {
  const root = document.querySelector(".ps-nav-root");
  if (!root) return;

  const btn = root.querySelector("[data-ps-nav-toggle]");
  const panel = root.querySelector("[data-ps-nav-panel]");
  if (!btn || !panel) return;

  function setOpen(open) {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    root.classList.toggle("is-open", open);
  }

  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    setOpen(panel.hidden);
  });

  panel.addEventListener("click", function (e) {
    e.stopPropagation();
  });

  document.addEventListener("click", function () {
    setOpen(false);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") setOpen(false);
  });
})();
