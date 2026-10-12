"use strict";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/staff/sw.js", { scope: "/staff/" }).catch(() => {});
  });
}
