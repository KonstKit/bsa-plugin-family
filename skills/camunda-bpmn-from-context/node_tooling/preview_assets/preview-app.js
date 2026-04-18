(() => {
  const runtime = {
    imported: false,
    lastZoom: 1,
    networkRequired: false,
    errors: [],
    versionStamp: null,
    metadataSummary: null,
    typedIssueTargets: null,
    sequenceFlowCount: 0,
    renderedConnectionCount: 0,
    shapeCount: 0,
    edgeDiCountFromManifestPreviewReport: null,
    expectedConnectionCount: 0,
    expectedSequenceFlowCount: 0,
    connectionLayerConsistent: false
  };
  window.__previewRuntime = runtime;

  function readJsonPayload(id) {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`missing payload: ${id}`);
    }
    return JSON.parse(node.textContent);
  }

  function readXmlPayload(id) {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`missing xml payload: ${id}`);
    }
    return node.textContent;
  }

  function setZoomText(value) {
    const target = document.getElementById('zoom-indicator');
    if (!target) {
      return;
    }
    target.textContent = `${Math.round(value * 100)}%`;
  }

  function showError(message) {
    runtime.errors.push(String(message));
    const banner = document.getElementById('preview-error');
    if (banner) {
      banner.textContent = String(message);
      banner.classList.add('is-visible');
    }
  }

  function renderVersionStamp(versionInfo) {
    runtime.versionStamp = versionInfo;
    const target = document.getElementById('version-stamp');
    if (!target) {
      return;
    }
    target.replaceChildren();
    const entries = [
      ['skill_version', versionInfo.skill_version],
      ['preview_schema_version', versionInfo.preview_schema_version],
      ['build_timestamp', versionInfo.build_timestamp]
    ];
    entries.forEach(([label, value]) => {
      const row = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = String(label);
      row.appendChild(strong);
      row.append(': ');
      row.appendChild(document.createTextNode(String(value)));
      target.appendChild(row);
    });
  }

  function renderManifestSummary(summary) {
    const mapping = {
      'manifest-requested-mode': summary.requested_mode,
      'manifest-final-backend': summary.final_backend,
      'manifest-fallback': String(summary.fallback_happened),
      'manifest-semantic-status': summary.semantic_status,
      'manifest-layout-status': summary.layout_status,
      'manifest-preview-status': summary.preview_status,
      'manifest-scenario-id': summary.scenario_id || 'n/a',
      'manifest-fixture-id': summary.fixture_id || 'n/a'
    };
    Object.entries(mapping).forEach(([id, value]) => {
      const target = document.getElementById(id);
      if (target) {
        target.textContent = String(value);
      }
    });
  }

  function renderMetadataSummary(summary) {
    runtime.metadataSummary = summary;
    runtime.edgeDiCountFromManifestPreviewReport = Number(summary.bpmn_edge_count ?? 0);
    runtime.expectedConnectionCount = Number(summary.bpmn_edge_count ?? 0);
    runtime.expectedSequenceFlowCount = Number(summary.sequence_flow_count ?? 0);
    const target = document.getElementById('metadata-summary');
    if (!target) {
      return;
    }
    const lines = [
      `build_version: ${summary.build_version}`,
      `skill_version: ${summary.skill_version}`,
      `runtime_target: ${summary.runtime_target}`,
      `manifest_schema_version: ${summary.manifest_schema_version}`,
      `linked_report_schema_version: ${summary.linked_report_schema_version}`,
      `scenario_id: ${summary.scenario_id}`,
      `fixture_id: ${summary.fixture_id}`,
      `traceability_count: ${summary.traceability_count}`,
      `assumptions_count: ${summary.assumptions_count}`,
      `fallback_reason_code: ${summary.fallback_reason_code}`,
      `typed_issue_count: ${summary.typed_issue_count}`,
      `typed_issue_target_count: ${summary.typed_issue_target_count}`,
      `warning_issue_count: ${summary.warning_issue_count}`,
      `error_issue_count: ${summary.error_issue_count}`,
      `layout_final_mode: ${summary.layout_final_mode}`,
      `layout_profile_family: ${summary.layout_profile_family}`,
      `advisory_only: ${String(summary.advisory_only)}`,
      `layout_requires_decomposition: ${String(summary.layout_requires_decomposition)}`,
      `diagram_width_px: ${summary.diagram_width_px}`,
      `diagram_height_px: ${summary.diagram_height_px}`,
      `aspect_ratio_x100: ${summary.aspect_ratio_x100}`,
      `max_depth_columns: ${summary.max_depth_columns}`,
      `max_edge_span_columns: ${summary.max_edge_span_columns}`,
      `consecutive_gateway_chain_length: ${summary.consecutive_gateway_chain_length}`,
      `readability_violations: ${summary.readability_violations}`,
      `sequence_flow_count: ${summary.sequence_flow_count}`,
      `bpmn_edge_count: ${summary.bpmn_edge_count}`,
      `bpmn_shape_count: ${summary.bpmn_shape_count}`,
      `expected_connection_count: ${runtime.expectedConnectionCount}`,
      `highlight_policy_phase: ${summary.highlight_policy_phase}`
    ];
    target.textContent = lines.join('\n');
  }

  function renderTypedIssueSummary(payload) {
    runtime.typedIssueTargets = payload;
    const target = document.getElementById('typed-issue-summary');
    if (!target) {
      return;
    }

    const counts = payload.counts || {};
    const byTargetType = counts.by_target_type || {};
    const bySeverity = counts.by_severity || {};
    const lines = [
      `total: ${counts.total || 0}`,
      `by_target_type: shape=${byTargetType.shape || 0}, edge=${byTargetType.edge || 0}, label=${byTargetType.label || 0}, pair=${byTargetType.pair || 0}, global=${byTargetType.global || 0}`,
      `by_severity: error=${bySeverity.error || 0}, warning=${bySeverity.warning || 0}, info=${bySeverity.info || 0}`
    ];

    const globalIssues = Array.isArray(payload.items)
      ? payload.items.filter((issue) => issue.target_type === 'global')
      : [];
    if (globalIssues.length > 0) {
      lines.push('global_issues_text_only:');
      globalIssues.slice(0, 6).forEach((issue) => {
        lines.push(`- ${issue.code}: ${issue.message}`);
      });
    } else {
      lines.push('global_issues_text_only: none');
    }
    lines.push('interactive_highlight: deferred_phase_5');
    target.textContent = lines.join('\n');
  }

  function renderReportSummary(summary) {
    const target = document.getElementById('report-summary');
    if (!target) {
      return;
    }
    target.textContent = summary.text;
  }

  function fitViewport(viewer) {
    const canvas = viewer.get('canvas');
    const summary = runtime.metadataSummary || {};
    const veryWide =
      Number(summary.aspect_ratio_x100 || 0) >= 420 ||
      Number(summary.diagram_width_px || 0) >= 1800;
    const requiresDecomposition = Boolean(summary.layout_requires_decomposition);
    if (veryWide || requiresDecomposition) {
      canvas.zoom(1.0, 'auto');
      runtime.lastZoom = Number(canvas.zoom()) || 1;
      setZoomText(runtime.lastZoom);
      return;
    }
    canvas.zoom('fit-viewport', 'auto');
    runtime.lastZoom = Number(canvas.zoom()) || 1;
    setZoomText(runtime.lastZoom);
  }

  function bindControls(viewer) {
    const canvas = viewer.get('canvas');
    const nudge = (dx, dy) => {
      const box = canvas.viewbox();
      canvas.viewbox({ ...box, x: box.x + dx, y: box.y + dy });
    };
    const adjustZoom = (delta) => {
      const current = Number(canvas.zoom()) || 1;
      const next = Math.max(0.2, Math.min(4, current + delta));
      canvas.zoom(next);
      runtime.lastZoom = next;
      setZoomText(next);
    };

    const bindings = {
      'zoom-in': () => adjustZoom(0.15),
      'zoom-out': () => adjustZoom(-0.15),
      'zoom-reset': () => fitViewport(viewer),
      'pan-up': () => nudge(0, -50),
      'pan-down': () => nudge(0, 50),
      'pan-left': () => nudge(-50, 0),
      'pan-right': () => nudge(50, 0)
    };

    Object.entries(bindings).forEach(([id, handler]) => {
      const button = document.getElementById(id);
      if (button) {
        button.addEventListener('click', handler);
      }
    });
  }

  function updateRenderedGraphCounts(viewer) {
    const elementRegistry = viewer.get('elementRegistry');
    const elements = elementRegistry.getAll();
    let sequenceFlowCount = 0;
    let renderedConnectionCount = 0;
    let shapeCount = 0;

    elements.forEach((element) => {
      if (element && typeof element.type === 'string' && element.type === 'bpmn:SequenceFlow') {
        sequenceFlowCount += 1;
      }
      if (element && Array.isArray(element.waypoints) && element.waypoints.length >= 2) {
        renderedConnectionCount += 1;
      }
      if (element && typeof element.width === 'number' && typeof element.height === 'number') {
        shapeCount += 1;
      }
    });

    runtime.sequenceFlowCount = sequenceFlowCount;
    runtime.renderedConnectionCount = renderedConnectionCount;
    runtime.shapeCount = shapeCount;
    runtime.connectionLayerConsistent =
      runtime.renderedConnectionCount === runtime.edgeDiCountFromManifestPreviewReport &&
      runtime.renderedConnectionCount === runtime.expectedConnectionCount &&
      runtime.sequenceFlowCount === runtime.expectedSequenceFlowCount;
  }

  async function init() {
    try {
      if (typeof window.BpmnJS !== 'function') {
        throw new Error('BpmnJS viewer bundle is unavailable');
      }
      const manifestSummary = readJsonPayload('preview-manifest-summary');
      const metadataSummary = readJsonPayload('preview-metadata-summary');
      const reportSummary = readJsonPayload('preview-report-summary');
      const typedIssueTargets = readJsonPayload('preview-typed-issue-targets');
      const versionInfo = readJsonPayload('preview-version-info');
      const xml = readXmlPayload('preview-bpmn-xml');

      renderVersionStamp(versionInfo);
      renderManifestSummary(manifestSummary);
      renderMetadataSummary(metadataSummary);
      renderTypedIssueSummary(typedIssueTargets);
      renderReportSummary(reportSummary);

      const viewer = new window.BpmnJS({
        container: '#preview-canvas'
      });
      runtime.viewer = viewer;
      runtime.xmlLength = xml.length;
      await viewer.importXML(xml);
      fitViewport(viewer);
      bindControls(viewer);
      updateRenderedGraphCounts(viewer);
      runtime.imported = true;
    } catch (error) {
      showError(error && error.message ? error.message : error);
    }
  }

  window.addEventListener('DOMContentLoaded', init, { once: true });
})();
