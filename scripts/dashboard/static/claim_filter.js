// BSA dashboard — filter helper for non-table containers (claim cards,
// trace groups). Same vanilla pattern as filterable_table.js but
// targets `.filterable-row` elements directly. v1.3.3.

(function () {
  "use strict";
  var input = document.getElementById("filter-input");
  var counter = document.getElementById("filter-count");
  if (!input) { return; }
  var rows = Array.prototype.slice.call(document.querySelectorAll(".filterable-row"));
  var totalRows = rows.length;

  function applyFilter() {
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
  input.addEventListener("input", applyFilter);
})();
