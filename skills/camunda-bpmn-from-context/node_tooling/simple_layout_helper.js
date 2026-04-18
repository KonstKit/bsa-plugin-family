#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn";
const ZEEBE_NS = "http://camunda.org/schema/zeebe/1.0";

function parseArgs(argv) {
  const args = { input: null, output: null, diagnostics: null };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--input") {
      args.input = argv[i + 1] || null;
      i += 1;
    } else if (token === "--output") {
      args.output = argv[i + 1] || null;
      i += 1;
    } else if (token === "--diagnostics") {
      args.diagnostics = argv[i + 1] || null;
      i += 1;
    }
  }
  return args;
}

function parseRuntimeTarget(xmlText) {
  if (!xmlText || typeof xmlText !== "string") {
    return {
      namespace_uris_detected: [],
      requires_namespace_preservation: false,
      requires_extension_preservation: false,
    };
  }
  const matches = Array.from(xmlText.matchAll(/\sxmlns(?::[A-Za-z_][\w.-]*)?="([^"]+)"/g));
  const namespaceUris = new Set(matches.map((match) => match[1]).filter(Boolean));
  const runtimeUris = [CAMUNDA_NS, ZEEBE_NS].filter((uri) => namespaceUris.has(uri));
  const requiresPreservation = runtimeUris.length > 0;
  return {
    namespace_uris_detected: runtimeUris.sort(),
    requires_namespace_preservation: requiresPreservation,
    requires_extension_preservation: requiresPreservation,
  };
}

function resolveLayoutMetadata() {
  let version = "unknown";
  try {
    const packageJsonPath = require.resolve("bpmn-auto-layout/package.json");
    const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
    if (packageJson && typeof packageJson.version === "string" && packageJson.version.trim()) {
      version = packageJson.version.trim();
    }
  } catch (_error) {
    // Metadata discovery failure must not break layout flow.
  }
  return {
    engine: "bpmn-auto-layout",
    version,
    node: process.versions.node || "unknown",
  };
}

function inspectDiCompleteness(xmlText) {
  const sequenceFlowCount = (xmlText.match(/<(?:[A-Za-z_][\w.-]*:)?sequenceFlow\b/g) || []).length;
  const bpmnShapeCount = (xmlText.match(/<(?:[A-Za-z_][\w.-]*:)?BPMNShape\b/g) || []).length;
  const edgeBlocks =
    xmlText.match(/<(?:[A-Za-z_][\w.-]*:)?BPMNEdge\b[\s\S]*?<\/(?:[A-Za-z_][\w.-]*:)?BPMNEdge>/g) || [];
  const bpmnEdgeCount = edgeBlocks.length;
  const edgeWithoutTwoWaypointsCount = edgeBlocks.reduce((count, block) => {
    const waypointCount = (block.match(/<(?:[A-Za-z_][\w.-]*:)?waypoint\b/g) || []).length;
    return count + (waypointCount < 2 ? 1 : 0);
  }, 0);
  const edgeDiComplete =
    sequenceFlowCount === 0 ||
    (bpmnEdgeCount >= sequenceFlowCount && edgeWithoutTwoWaypointsCount === 0);
  return {
    sequence_flow_count: sequenceFlowCount,
    bpmn_shape_count: bpmnShapeCount,
    bpmn_edge_count: bpmnEdgeCount,
    edge_without_two_waypoints_count: edgeWithoutTwoWaypointsCount,
    edge_di_complete: edgeDiComplete
  };
}

function classifyDiQuality(stats) {
  if (!stats || (stats.bpmn_shape_count <= 0 && stats.bpmn_edge_count <= 0)) {
    return "no_di";
  }
  if (stats.sequence_flow_count > 0 && !stats.edge_di_complete) {
    return "partial_di";
  }
  return "usable_di";
}

function writeDiagnostics(filePath, status, errors, runtimeTarget, metadata, outputStats) {
  const engineMetadata = metadata || resolveLayoutMetadata();
  const stats = outputStats || {
    sequence_flow_count: 0,
    bpmn_shape_count: 0,
    bpmn_edge_count: 0,
    edge_without_two_waypoints_count: 0,
    edge_di_complete: false
  };
  const payload = {
    version: "1.0",
    status,
    errors,
    warnings: [
      `layout_engine=${engineMetadata.engine}@${engineMetadata.version}`,
      `node_runtime=${engineMetadata.node}`,
    ],
    helper: {
      launched: true,
      command: process.argv.slice(0),
      returncode: status === "PASS" ? 0 : 1,
    },
    output: {
      bpmn_written: status === "PASS",
      sequence_flow_count: Number.isInteger(stats.sequence_flow_count) ? stats.sequence_flow_count : 0,
      bpmn_shape_count: Number.isInteger(stats.bpmn_shape_count) ? stats.bpmn_shape_count : 0,
      bpmn_edge_count: Number.isInteger(stats.bpmn_edge_count) ? stats.bpmn_edge_count : 0,
      edge_without_two_waypoints_count: Number.isInteger(stats.edge_without_two_waypoints_count)
        ? stats.edge_without_two_waypoints_count
        : 0,
      edge_di_complete: Boolean(stats.edge_di_complete),
      di_quality: classifyDiQuality(stats),
    },
    runtime_target: runtimeTarget || {
      namespace_uris_detected: [],
      requires_namespace_preservation: false,
      requires_extension_preservation: false,
    },
  };
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2) + "\n", "utf8");
}

async function layoutBpmnXml(inputXml) {
  const layoutModule = await import("bpmn-auto-layout");
  const layoutProcess =
    layoutModule.layoutProcess ||
    (layoutModule.default && layoutModule.default.layoutProcess) ||
    layoutModule.default;
  if (typeof layoutProcess !== "function") {
    throw new Error("bpmn-auto-layout layoutProcess export is unavailable");
  }
  const outputXml = await layoutProcess(inputXml);
  if (typeof outputXml !== "string" || !outputXml.trim()) {
    throw new Error("bpmn-auto-layout returned empty diagram");
  }
  return outputXml;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.input || !args.output || !args.diagnostics) {
    const missing = [];
    if (!args.input) missing.push("--input");
    if (!args.output) missing.push("--output");
    if (!args.diagnostics) missing.push("--diagnostics");
    const message = `missing required helper args: ${missing.join(", ")}`;
    if (args.diagnostics) {
      writeDiagnostics(args.diagnostics, "FAIL", [message], null, null, null);
    }
    console.error(message);
    return 1;
  }

  try {
    const inputXml = fs.readFileSync(args.input, "utf8");
    const runtimeTarget = parseRuntimeTarget(inputXml);
    const metadata = resolveLayoutMetadata();
    const outputXml = await layoutBpmnXml(inputXml);
    const outputStats = inspectDiCompleteness(outputXml);

    fs.mkdirSync(path.dirname(args.output), { recursive: true });
    fs.writeFileSync(args.output, outputXml, "utf8");
    writeDiagnostics(args.diagnostics, "PASS", [], runtimeTarget, metadata, outputStats);
    return 0;
  } catch (error) {
    writeDiagnostics(args.diagnostics, "FAIL", [String(error && error.message ? error.message : error)], null, null, null);
    console.error(String(error && error.message ? error.message : error));
    return 1;
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(String(error && error.message ? error.message : error));
    process.exit(1);
  },
);
