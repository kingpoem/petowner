"use strict";

// 经营报表筛选：点选快捷周期立即刷新；修改起止日期时自动切换为“自定义”。
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".ps-report-filter");
  if (!form) return;
  form.addEventListener("change", (e) => {
    const { name, value } = e.target;
    if (name === "preset" && value !== "custom") form.requestSubmit();
    if (name === "start" || name === "end") form.querySelector('input[name="preset"][value="custom"]').checked = true;
  });
});
