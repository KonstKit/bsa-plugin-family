// BSA dashboard — keyboard shortcuts.
// v1.3.5. Vanilla, ~70 LOC.
//
// Bindings:
//   /         → focus search box
//   Escape    → blur active input + close search results
//   g then o  → Overview
//   g then a  → Artifacts (if rendered)
//   g then u  → aUdits (if rendered)
//   g then h  → Handoff (if rendered)
//   g then c  → Contracts (if rendered)
//   g then d  → Diagrams (sidecars; if rendered)
//   g then p  → Phase 7 (if rendered)
//
// v1.3.5 R1 MINOR fix: nav targets are derived from the actual
// rendered nav links, NOT hard-coded. So `--filter audits` won't
// route `g a` to a non-existent artifacts/index.html.

(function () {
  "use strict";
  var pendingG = false;
  var pendingGTimer = null;

  function isTypingTarget(el) {
    if (!el) { return false; }
    var tag = (el.tagName || "").toUpperCase();
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
           el.isContentEditable;
  }

  // Extract nav targets from rendered <a> tags inside .site-nav.
  // Each anchor's href is page-local (e.g., "audits/index.html" or
  // "../audits/index.html" depending on depth); we just navigate to
  // it directly — no need to know the root_prefix.
  //
  // Overview detection: it's always the first nav <a>, AND it's the
  // only one whose href doesn't contain any of the section dir names.
  // Pre-R2-fix the check `href.indexOf("/") === -1` was wrong on
  // subpages where Overview href is `../index.html`.
  var SECTION_DIRS = [
    "artifacts/", "audits/", "handoff/", "contracts/",
    "sidecars/", "phase7/",
  ];

  function navTargets() {
    var targets = {};
    var anchors = document.querySelectorAll(".site-nav a");
    anchors.forEach(function (a, idx) {
      var href = a.getAttribute("href") || "";
      // Overview = first anchor (by document order in base.html
      // template) AND href doesn't contain any section dir.
      var isSection = SECTION_DIRS.some(function (d) {
        return href.indexOf(d) !== -1;
      });
      if (!isSection && idx === 0) {
        targets["o"] = href;
      } else if (href.indexOf("artifacts/") !== -1) {
        targets["a"] = href;
      } else if (href.indexOf("audits/") !== -1) {
        targets["u"] = href;
      } else if (href.indexOf("handoff/") !== -1) {
        targets["h"] = href;
      } else if (href.indexOf("contracts/") !== -1) {
        targets["c"] = href;
      } else if (href.indexOf("sidecars/") !== -1) {
        targets["d"] = href;
      } else if (href.indexOf("phase7/") !== -1) {
        targets["p"] = href;
      }
    });
    return targets;
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var results = document.getElementById("nav-search-results");
      if (results) { results.classList.remove("open"); }
      if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
      }
      pendingG = false;
      return;
    }
    if (isTypingTarget(e.target)) { return; }
    if (e.metaKey || e.ctrlKey || e.altKey) { return; }

    if (e.key === "/") {
      var input = document.getElementById("nav-search-input");
      if (input) {
        e.preventDefault();
        input.focus();
      }
      return;
    }

    if (e.key === "g") {
      pendingG = true;
      if (pendingGTimer) { clearTimeout(pendingGTimer); }
      pendingGTimer = setTimeout(function () { pendingG = false; }, 1500);
      return;
    }

    if (pendingG) {
      pendingG = false;
      if (pendingGTimer) { clearTimeout(pendingGTimer); pendingGTimer = null; }
      var targets = navTargets();
      var href = targets[e.key];
      if (href) {
        window.location.href = href;
      }
    }
  });
})();
