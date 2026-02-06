/* Minimal local JS for static/offline pages (no Thrive/WP deps). */

(function () {
  "use strict";

  function initTabs() {
    const tabWrappers = document.querySelectorAll(
      ".thrv_tabs_shortcode .tve_scT"
    );

    tabWrappers.forEach((wrapper, wrapperIndex) => {
      const tabList = wrapper.querySelector(".tve_tabs_wrapper ul");
      const tabs = Array.from(wrapper.querySelectorAll(".tve_tabs_wrapper li"));
      const panels = Array.from(wrapper.querySelectorAll(".tve_scTC"));

      if (!tabs.length || !panels.length) return;

      if (tabList) tabList.setAttribute("role", "tablist");

      function getPanelKeyForTab(tabEl) {
        const span = tabEl.querySelector("span");
        if (!span) return null;
        const match = span.className.match(/tve_scTC\d+/);
        return match ? match[0] : null;
      }

      function setActiveTab(activeIndex) {
        tabs.forEach((tabEl, idx) => {
          const isActive = idx === activeIndex;
          tabEl.classList.toggle("tve-state-expanded", isActive);
          tabEl.classList.toggle("tve-state-collapsed", !isActive);
          tabEl.setAttribute("role", "tab");
          tabEl.setAttribute("tabindex", isActive ? "0" : "-1");
          tabEl.setAttribute("aria-selected", isActive ? "true" : "false");

          const panelKey = getPanelKeyForTab(tabEl);
          tabEl.dataset.panelKey = panelKey || "";

          if (!tabEl.id) {
            tabEl.id = `tab-${wrapperIndex}-${idx}`;
          }
        });

        const activeKey = tabs[activeIndex].dataset.panelKey;

        panels.forEach((panelEl, idx) => {
          const panelHasKey = activeKey && panelEl.classList.contains(activeKey);
          const isPanelActive = panelHasKey || (!activeKey && idx === activeIndex);

          panelEl.style.display = isPanelActive ? "block" : "none";
          panelEl.classList.toggle("tve-tc-visible", isPanelActive);
          panelEl.setAttribute("role", "tabpanel");

          if (!panelEl.id) {
            panelEl.id = `panel-${wrapperIndex}-${idx}`;
          }
        });
      }

      // initial active tab: from data-selected or existing expanded class
      let initialIndex = 0;
      const dataSelected = wrapper.getAttribute("data-selected");
      if (dataSelected && !Number.isNaN(Number(dataSelected))) {
        initialIndex = Math.max(0, Math.min(tabs.length - 1, Number(dataSelected)));
      } else {
        const expandedIndex = tabs.findIndex((t) => t.classList.contains("tve-state-expanded"));
        if (expandedIndex >= 0) initialIndex = expandedIndex;
      }

      setActiveTab(initialIndex);

      tabs.forEach((tabEl, idx) => {
        tabEl.addEventListener("click", (e) => {
          e.preventDefault();
          setActiveTab(idx);
        });

        tabEl.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
          e.preventDefault();

          let nextIndex = idx;
          if (e.key === "ArrowLeft") nextIndex = (idx - 1 + tabs.length) % tabs.length;
          if (e.key === "ArrowRight") nextIndex = (idx + 1) % tabs.length;
          if (e.key === "Home") nextIndex = 0;
          if (e.key === "End") nextIndex = tabs.length - 1;

          setActiveTab(nextIndex);
          tabs[nextIndex].focus();
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTabs);
  } else {
    initTabs();
  }
})();
