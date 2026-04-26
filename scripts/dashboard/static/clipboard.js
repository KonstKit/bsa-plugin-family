// BSA dashboard — minimal clipboard helper for "Copy" buttons.
// v1.3.3. Vanilla, ~25 LOC.

(function () {
  "use strict";
  var buttons = document.querySelectorAll(".copy-button[data-clipboard-target]");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sel = btn.getAttribute("data-clipboard-target");
      var target = document.querySelector(sel);
      if (!target) { return; }
      var text = target.textContent;
      function flash() {
        var orig = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(function () { btn.textContent = orig; }, 1500);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(flash);
      } else {
        var range = document.createRange();
        range.selectNode(target);
        var sel2 = window.getSelection();
        sel2.removeAllRanges();
        sel2.addRange(range);
        try { document.execCommand("copy"); flash(); } catch (e) { /* noop */ }
        sel2.removeAllRanges();
      }
    });
  });
})();
