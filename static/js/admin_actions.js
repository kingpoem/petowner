(() => {
  const root = document.getElementById("ps-actions");
  if (!root) return;

  const native = root.querySelector(".ps-action-native");
  const deleteBtn = root.querySelector('[data-ps-action="delete_selected"]');
  const moreWrap = root.querySelector("#ps-actions-more");
  const moreSelect = root.querySelector("#ps-action-more");
  const moreBtn = root.querySelector(".ps-btn-more");
  if (!native) return;

  const options = Array.from(native.options).filter((opt) => opt.value);
  const hasDelete = options.some((opt) => opt.value === "delete_selected");
  const others = options.filter((opt) => opt.value !== "delete_selected");

  if (hasDelete && deleteBtn) {
    deleteBtn.hidden = false;
    deleteBtn.addEventListener("click", (event) => {
      const checked = document.querySelectorAll("#changelist tbody input.action-select:checked");
      if (!checked.length) {
        event.preventDefault();
        window.alert("请先勾选要删除的项目。");
        return;
      }
      if (!window.confirm("确定删除所选项目？删除后通常无法恢复。")) {
        event.preventDefault();
        return;
      }
      native.value = "delete_selected";
    });
  }

  if (others.length && moreWrap && moreSelect && moreBtn) {
    moreWrap.hidden = false;
    for (const opt of others) {
      const item = document.createElement("option");
      item.value = opt.value;
      item.textContent = opt.textContent;
      moreSelect.appendChild(item);
    }
    moreSelect.value = others[0].value;
    moreBtn.addEventListener("click", (event) => {
      const checked = document.querySelectorAll("#changelist tbody input.action-select:checked");
      if (!checked.length) {
        event.preventDefault();
        window.alert("请先勾选要操作的项目。");
        return;
      }
      const action = moreSelect.value;
      if (action.startsWith("cancel_")) {
        const label = moreSelect.options[moreSelect.selectedIndex].textContent.trim();
        if (!window.confirm(`确定对所选订单执行「${label}」？`)) {
          event.preventDefault();
          return;
        }
      }
      native.value = action;
    });
  }
})();
