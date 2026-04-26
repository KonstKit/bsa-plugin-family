// BSA dashboard — client-side filter + sort for artifact tables.
// Vanilla JS, ~50 LOC, no framework. v1.3.3.

(function () {
  "use strict";
  var input = document.getElementById("filter-input");
  var counter = document.getElementById("filter-count");
  var table = document.querySelector(".artifact-table");
  if (!table) { return; }
  var tbody = table.querySelector("tbody");
  var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
  var totalRows = rows.length;

  function applyFilter() {
    if (!input) { return; }
    var q = input.value.trim().toLowerCase();
    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
      var match = q === "" || rows[i].textContent.toLowerCase().indexOf(q) !== -1;
      rows[i].style.display = match ? "" : "none";
      if (match) { visible++; }
    }
    if (counter) {
      counter.textContent = visible + " / " + totalRows;
    }
  }
  if (input) {
    input.addEventListener("input", applyFilter);
  }

  // Click-to-sort headers.
  var headers = table.querySelectorAll("thead th.sortable");
  var sortState = { col: -1, asc: true };
  headers.forEach(function (th) {
    th.addEventListener("click", function () {
      var col = parseInt(th.getAttribute("data-col"), 10);
      if (sortState.col === col) {
        sortState.asc = !sortState.asc;
      } else {
        sortState.col = col;
        sortState.asc = true;
      }
      headers.forEach(function (h) {
        var ind = h.querySelector(".sort-indicator");
        if (ind) { ind.textContent = ""; }
      });
      var indicator = th.querySelector(".sort-indicator");
      if (indicator) {
        indicator.textContent = sortState.asc ? " ↑" : " ↓";
      }
      var sorted = rows.slice().sort(function (a, b) {
        var av = a.cells[col] ? a.cells[col].textContent.trim() : "";
        var bv = b.cells[col] ? b.cells[col].textContent.trim() : "";
        var an = parseFloat(av), bn = parseFloat(bv);
        var cmp;
        if (!isNaN(an) && !isNaN(bn)) {
          cmp = an - bn;
        } else {
          cmp = av.localeCompare(bv);
        }
        return sortState.asc ? cmp : -cmp;
      });
      var frag = document.createDocumentFragment();
      sorted.forEach(function (r) { frag.appendChild(r); });
      tbody.appendChild(frag);
      rows = sorted;
    });
  });
})();
