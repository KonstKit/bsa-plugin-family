// BSA dashboard — full-text search across all rendered pages.
// v1.3.5. Vanilla, ~110 LOC.
//
// Reads window.__BSA_SEARCH_INDEX__ (assigned by search_index.js,
// loaded via <script src> in base.html — works on file:// because
// fetch() is blocked for local files in modern browsers).
//
// All result rendering uses DOM APIs (createElement + textContent +
// .href = ...) — NOT innerHTML — so untrusted strings (e.g., A-table
// primary-key values from operator CSVs) cannot inject HTML/JS.
// v1.3.5 R1 fix #3 (XSS via search results innerHTML).

(function () {
  "use strict";
  var input = document.getElementById("nav-search-input");
  var results = document.getElementById("nav-search-results");
  if (!input || !results) { return; }
  var rootPrefix = input.getAttribute("data-root-prefix") || "";

  function getEntries() {
    var doc = window.__BSA_SEARCH_INDEX__;
    if (!doc || !Array.isArray(doc.entries)) { return []; }
    return doc.entries;
  }

  function clearChildren(el) {
    while (el.firstChild) { el.removeChild(el.firstChild); }
  }

  function renderEmpty(query) {
    clearChildren(results);
    var div = document.createElement("div");
    div.className = "search-result-empty";
    div.textContent = 'No matches for "' + query + '"';
    results.appendChild(div);
    results.classList.add("open");
  }

  function renderResults(matches, query) {
    clearChildren(results);
    if (matches.length === 0) {
      renderEmpty(query);
      return;
    }
    matches.slice(0, 30).forEach(function (entry) {
      var a = document.createElement("a");
      a.className = "search-result";
      // .href setter assignment correctly URI-encodes; .setAttribute
      // would also escape attribute quotes. Either way safe.
      a.href = rootPrefix + entry.url;

      var titleDiv = document.createElement("div");
      titleDiv.className = "search-result-title";
      var section = document.createElement("span");
      section.className = "search-result-section";
      section.textContent = String(entry.section || "");
      titleDiv.appendChild(section);
      titleDiv.appendChild(document.createTextNode(" " + (entry.title || "")));
      a.appendChild(titleDiv);

      var snippet = extractSnippet(entry.text || "", query, 80);
      if (snippet) {
        var snippetDiv = document.createElement("div");
        snippetDiv.className = "search-result-snippet";
        snippetDiv.textContent = snippet;
        a.appendChild(snippetDiv);
      }
      results.appendChild(a);
    });
    if (matches.length > 30) {
      var more = document.createElement("div");
      more.className = "search-result-empty";
      more.textContent =
        "… plus " + (matches.length - 30) + " more (refine your query)";
      results.appendChild(more);
    }
    results.classList.add("open");
  }

  function extractSnippet(text, query, maxLen) {
    if (!text || !query) { return ""; }
    var lower = text.toLowerCase();
    var idx = lower.indexOf(query.toLowerCase());
    if (idx === -1) { return text.slice(0, maxLen); }
    var start = Math.max(0, idx - 30);
    var end = Math.min(text.length, idx + query.length + 30);
    return (start > 0 ? "…" : "") + text.slice(start, end) +
      (end < text.length ? "…" : "");
  }

  function onInput() {
    var q = input.value.trim();
    if (q.length < 2) {
      results.classList.remove("open");
      return;
    }
    var entries = getEntries();
    var lq = q.toLowerCase();
    var matches = entries.filter(function (e) {
      return (e.title || "").toLowerCase().indexOf(lq) !== -1 ||
             (e.text || "").toLowerCase().indexOf(lq) !== -1;
    });
    renderResults(matches, q);
  }

  input.addEventListener("input", onInput);
  input.addEventListener("focus", onInput);
  document.addEventListener("click", function (e) {
    if (!results.contains(e.target) && e.target !== input) {
      results.classList.remove("open");
    }
  });
})();
