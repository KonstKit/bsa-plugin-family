// BSA dashboard — Chart.js init for Phase 7 KPI trend lines.
// v1.3.5. Vanilla, ~40 LOC.

(function () {
  "use strict";
  if (typeof Chart === "undefined") {
    document.querySelectorAll(".kpi-chart-card canvas").forEach(function (c) {
      c.outerHTML = '<div class="bpmn-error">Chart.js not loaded — check that scripts/dashboard/static/vendor/chart.umd.js is present.</div>';
    });
    return;
  }
  var dataNode = document.getElementById("kpi-series-data");
  if (!dataNode) { return; }
  var seriesList;
  try {
    seriesList = JSON.parse(dataNode.textContent || "[]");
  } catch (e) {
    console.warn("KPI series JSON parse failed:", e);
    return;
  }
  // Detect dark mode for chart axis/grid colors.
  var isDark = window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  var axisColor = isDark ? "#a0a0a0" : "#6b6b6b";
  var gridColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  var lineColor = isDark ? "#60a5fa" : "#2563eb";
  var pointColor = isDark ? "#93c5fd" : "#1d4ed8";

  seriesList.forEach(function (series, idx) {
    var canvas = document.getElementById("kpi-chart-" + idx);
    if (!canvas) { return; }
    var labels = series.runs.map(function (r) { return r.timestamp || r.run_id; });
    var values = series.runs.map(function (r) { return r.value; });
    new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [{
          label: series.label,
          data: values,
          borderColor: lineColor,
          backgroundColor: lineColor + "33",
          pointBackgroundColor: pointColor,
          tension: 0.2,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {legend: {display: false}},
        scales: {
          x: {
            ticks: {color: axisColor, maxTicksLimit: 6, autoSkip: true},
            grid: {color: gridColor},
          },
          y: {
            ticks: {color: axisColor},
            grid: {color: gridColor},
            beginAtZero: true,
          },
        },
      },
    });
  });
})();
