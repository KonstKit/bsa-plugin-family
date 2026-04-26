// BSA dashboard — bpmn-js inline viewer init for sidecars/bpmn.html.
// v1.3.5. Vanilla, ~50 LOC.

(function () {
  "use strict";
  if (typeof BpmnJS === "undefined") {
    // bpmn-js bundle didn't load (e.g., vendor/ missing); show error
    // in each container instead of failing silently.
    document.querySelectorAll(".bpmn-container").forEach(function (el) {
      el.innerHTML = '<div class="bpmn-error">bpmn-js viewer not loaded — check that scripts/dashboard/static/vendor/bpmn-navigated-viewer.js is present.</div>';
    });
    return;
  }
  document.querySelectorAll(".bpmn-container").forEach(function (container) {
    var sourceId = container.getAttribute("data-bpmn-source-id");
    if (!sourceId) { return; }
    var sourceEl = document.getElementById(sourceId);
    if (!sourceEl) { return; }
    // sourceEl is a <code> with HTML-escaped XML; .textContent gives
    // the unescaped raw XML which is what bpmn-js parses.
    var xml = sourceEl.textContent;
    var viewer = new BpmnJS({container: container});
    viewer.importXML(xml).then(function (result) {
      var warnings = result.warnings || [];
      if (warnings.length > 0) {
        console.warn("bpmn-js warnings for " + sourceId, warnings);
      }
      var canvas = viewer.get("canvas");
      canvas.zoom("fit-viewport");
    }).catch(function (err) {
      container.innerHTML = '<div class="bpmn-error">Failed to render BPMN: ' + (err.message || err) + '</div>';
    });
  });
})();
