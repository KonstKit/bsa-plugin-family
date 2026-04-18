#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function walk(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(fullPath));
    } else {
      files.push(fullPath);
    }
  }
  return files;
}

function normalizeAssetRef(rawRef) {
  const value = String(rawRef || '').trim();
  return value.replace(/^\.\//, '');
}

function isExternalRef(ref) {
  return /^(https?:)?\/\//i.test(ref);
}

function collectSrcsetRefs(rawValue) {
  return String(rawValue || '')
    .split(',')
    .map((part) => normalizeAssetRef(part.trim().split(/\s+/)[0]))
    .filter(Boolean);
}

function auditHtml(filePath, violations) {
  const html = fs.readFileSync(filePath, 'utf8');
  const attrPattern = /<(script|link|img|iframe|source)\b[^>]*\b(src|href|srcset)=['"]([^'"]+)['"]/gi;
  let match;
  while ((match = attrPattern.exec(html)) !== null) {
    const attribute = match[2].toLowerCase();
    const refs = attribute === 'srcset' ? collectSrcsetRefs(match[3]) : [normalizeAssetRef(match[3])];
    for (const ref of refs) {
      if (isExternalRef(ref)) {
        violations.push(`${path.basename(filePath)}: external ${attribute} reference ${ref}`);
      }
    }
  }
  const styleUrlPattern = /url\(([^)]+)\)/gi;
  while ((match = styleUrlPattern.exec(html)) !== null) {
    const ref = normalizeAssetRef(match[1].replace(/^['"]|['"]$/g, ''));
    if (isExternalRef(ref)) {
      violations.push(`${path.basename(filePath)}: external style url ${ref}`);
    }
  }
}

function auditCss(filePath, violations) {
  const css = fs.readFileSync(filePath, 'utf8');
  const importPattern = /@import\s+(?:url\()?['"]([^'"]+)['"]/gi;
  let match;
  while ((match = importPattern.exec(css)) !== null) {
    const ref = normalizeAssetRef(match[1]);
    if (isExternalRef(ref)) {
      violations.push(`${path.basename(filePath)}: external css import ${ref}`);
    }
  }
  const urlPattern = /url\(([^)]+)\)/gi;
  while ((match = urlPattern.exec(css)) !== null) {
    const ref = normalizeAssetRef(match[1].replace(/^['"]|['"]$/g, ''));
    if (isExternalRef(ref)) {
      violations.push(`${path.basename(filePath)}: external css url ${ref}`);
    }
  }
}

function auditJs(filePath, violations, relativePath) {
  const js = fs.readFileSync(filePath, 'utf8');
  const isVendorAsset = String(relativePath || '').startsWith('assets/vendor/');
  const externalUrlLiteralPattern = /['"`]\s*(?:https?:)?\/\//i;
  if (!isVendorAsset && externalUrlLiteralPattern.test(js)) {
    violations.push(`${path.basename(filePath)}: forbidden external URL literal in runtime JS`);
  }

  const forbidden = [
    { label: 'fetch()', pattern: /\bfetch\s*\(/ },
    { label: 'XMLHttpRequest', pattern: /\bXMLHttpRequest\b/ },
    { label: 'WebSocket', pattern: /\bWebSocket\b/ },
    { label: 'EventSource', pattern: /\bEventSource\b/ },
    { label: 'navigator.sendBeacon', pattern: /\bnavigator\s*\.\s*sendBeacon\s*\(/ },
    { label: 'new Image().src', pattern: /\bnew\s+Image\s*\(\s*\)\s*\.\s*src\s*=/ },
    { label: 'location.href', pattern: /\blocation\s*\.\s*href\s*=/ }
  ];
  for (const entry of forbidden) {
    if (entry.pattern.test(js)) {
      violations.push(`${path.basename(filePath)}: forbidden runtime network primitive ${entry.label}`);
    }
  }

  const navigationPatterns = [
    { label: 'location.assign', pattern: /\blocation\s*\.\s*assign\s*\(\s*['"`]\s*(https?:)?\/\//i },
    { label: 'window.open', pattern: /\bwindow\s*\.\s*open\s*\(\s*['"`]\s*(https?:)?\/\//i }
  ];
  for (const entry of navigationPatterns) {
    if (entry.pattern.test(js)) {
      violations.push(`${path.basename(filePath)}: forbidden runtime navigation primitive ${entry.label}`);
    }
  }
}

function auditRuntime(rootDir) {
  const target = path.resolve(rootDir);
  if (!fs.existsSync(target) || !fs.statSync(target).isDirectory()) {
    throw new Error(`runtime directory not found: ${target}`);
  }

  const files = walk(target);
  const violations = [];
  for (const filePath of files) {
    const relativePath = path.relative(target, filePath);
    if (filePath.endsWith('.html')) {
      auditHtml(filePath, violations);
    } else if (filePath.endsWith('.css')) {
      auditCss(filePath, violations);
    } else if (filePath.endsWith('.js')) {
      auditJs(filePath, violations, relativePath);
    }
  }

  const result = {
    ok: violations.length === 0,
    checkedFiles: files.map((filePath) => path.relative(target, filePath)).sort(),
    violations
  };

  if (!result.ok) {
    process.stderr.write(JSON.stringify(result, null, 2) + '\n');
    process.exit(1);
  }

  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

function main(argv) {
  const [command, runtimeDir] = argv;
  if (command !== 'audit-runtime') {
    throw new Error('usage: preview_builder.js audit-runtime <runtimeDir>');
  }
  if (!runtimeDir) {
    throw new Error('runtimeDir is required');
  }
  auditRuntime(runtimeDir);
}

if (require.main === module) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(String(error.message || error) + '\n');
    process.exit(1);
  }
}
