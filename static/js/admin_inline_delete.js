(() => {
  const bind = (cell) => {
    if (!(cell instanceof HTMLElement) || cell.dataset.psDeleteBound) return;
    const checkbox = cell.querySelector('input[type="checkbox"]');
    if (!checkbox) return;
    cell.dataset.psDeleteBound = "1";

    let btn = cell.querySelector(".ps-inline-delete");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ps-inline-delete";
      btn.setAttribute("aria-label", "删除");
      btn.title = "删除";
      btn.textContent = "×";
      cell.appendChild(btn);
    }

    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!window.confirm("确定删除这条记录？删除后将立即保存。")) return;
      checkbox.checked = true;
      const form = checkbox.closest("form");
      if (!form) return;
      let cont = form.querySelector('input[type="hidden"][name="_continue"]');
      if (!cont) {
        cont = document.createElement("input");
        cont.type = "hidden";
        cont.name = "_continue";
        form.appendChild(cont);
      }
      cont.value = "1";
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  };

  const scan = (root = document) => {
    root.querySelectorAll("td.delete").forEach(bind);
  };

  scan();
  document.addEventListener("formset:added", (event) => {
    const row = event.target;
    if (row instanceof HTMLElement) scan(row);
  });
})();
