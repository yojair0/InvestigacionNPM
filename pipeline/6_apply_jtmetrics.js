#!/usr/bin/env node
"use strict";

/**
 * Fase 4: Aplicacion de JTMetrics sobre metadata local de paquetes NPM.
 *
 * Entrada por defecto:
 *   data/metrics/packages_info.csv
 *
 * Salida por defecto:
 *   data/metrics/04_jtmetrics_resultados.csv
 */

const fs = require("fs");
const path = require("path");
const {
  buildCouplingGraph,
  computeImportInstability,
  computeDependencyCentrality,
  computePackageDependencySummary,
} = require("./jtmetrics/pure_metrics");
const { readCsvRows, createCsvWriter } = require("./jtmetrics/csv_io");

const DEFAULT_INPUT = path.join("data", "metrics", "packages_info.csv");
const DEFAULT_OUTPUT = path.join("data", "metrics", "04_jtmetrics_resultados.csv");

const OUTPUT_HEADERS = [
  "package",
  "version",
  "size_bytes",
  "file_count",
  "nonempty_file_count",
  "jt_afferent",
  "jt_efferent_total",
  "jt_efferent_internal",
  "jt_efferent_external",
  "jt_instability",
  "jt_in_degree",
  "jt_out_degree",
  "jt_in_degree_centrality",
  "jt_out_degree_centrality",
  "jt_total_degree_centrality",
  "jt_dependency_score",
  "jt_warning_count",
  "jt_warning_messages",
];

function parseArgs(argv) {
  const args = {
    input: DEFAULT_INPUT,
    output: DEFAULT_OUTPUT,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--input" && argv[i + 1]) {
      args.input = argv[i + 1];
      i += 1;
      continue;
    }
    if (token === "--output" && argv[i + 1]) {
      args.output = argv[i + 1];
      i += 1;
      continue;
    }
    if (token === "--help" || token === "-h") {
      args.help = true;
      break;
    }
  }

  return args;
}

function printHelp() {
  console.log("Uso:");
  console.log("  node pipeline/6_apply_jtmetrics.js [--input <csv>] [--output <csv>]");
  console.log("");
  console.log("Opciones:");
  console.log(`  --input   CSV de entrada (default: ${DEFAULT_INPUT})`);
  console.log(`  --output  CSV de salida  (default: ${DEFAULT_OUTPUT})`);
}

function warnMetric(packageName, metricName, error, warnings) {
  const msg = `[warn] paquete=${packageName} metrica=${metricName} detalle=${error?.message || error}`;
  warnings.push(msg);
  console.warn(msg);
}

function safeJsonMap(text, packageName, fieldName, warnings) {
  if (!text || text.trim() === "") {
    return {};
  }

  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    warnMetric(packageName, `parse_${fieldName}`, error, warnings);
    return {};
  }
}

function uniqueStringArray(values) {
  if (!Array.isArray(values)) {
    return [];
  }
  return Array.from(new Set(values.filter((x) => typeof x === "string" && x.length > 0)));
}

function parseIntSafe(value) {
  const parsed = Number.parseInt(String(value || "0"), 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

async function loadPackages(inputCsv) {
  const packages = [];
  const packageSet = new Set();

  await readCsvRows(inputCsv, async (row) => {
    const packageName = (row.package || "").trim();
    if (!packageName) {
      return;
    }

    packageSet.add(packageName);
    packages.push({
      package: packageName,
      version: (row.version || "").trim(),
      size_bytes: parseIntSafe(row.size_bytes),
      file_count: parseIntSafe(row.file_count),
      nonempty_file_count: parseIntSafe(row.nonempty_file_count),
      dependenciesRaw: row.dependencies || "{}",
      devDependenciesRaw: row.dev_dependencies || "{}",
    });
  });

  return { packages, packageSet };
}

function buildRawCouplingMaps(packages, packageSet) {
  const fullRawCoupling = {};
  const internalRawCoupling = {};
  const packageWarnings = new Map();

  for (const pkg of packages) {
    const warnings = [];
    packageWarnings.set(pkg.package, warnings);

    const deps = safeJsonMap(pkg.dependenciesRaw, pkg.package, "dependencies", warnings);
    const devDeps = safeJsonMap(pkg.devDependenciesRaw, pkg.package, "dev_dependencies", warnings);

    const allTargets = uniqueStringArray([...Object.keys(deps), ...Object.keys(devDeps)]);
    fullRawCoupling[pkg.package] = allTargets;
    internalRawCoupling[pkg.package] = allTargets.filter((dep) => packageSet.has(dep));
  }

  return { fullRawCoupling, internalRawCoupling, packageWarnings };
}

async function run() {
  const startedAt = Date.now();
  const args = parseArgs(process.argv.slice(2));

  if (args.help) {
    printHelp();
    return;
  }

  if (!fs.existsSync(args.input)) {
    throw new Error(`No existe el archivo de entrada: ${args.input}`);
  }

  console.log(`[jtmetrics] Cargando entrada: ${args.input}`);
  const { packages, packageSet } = await loadPackages(args.input);
  console.log(`[jtmetrics] Paquetes detectados: ${packages.length}`);

  const { fullRawCoupling, internalRawCoupling, packageWarnings } = buildRawCouplingMaps(packages, packageSet);

  let fullGraph = {};
  let internalGraph = {};
  try {
    fullGraph = buildCouplingGraph(fullRawCoupling);
  } catch (error) {
    console.warn(`[warn] buildCouplingGraph(full) fallo: ${error?.message || error}`);
    fullGraph = {};
  }

  try {
    internalGraph = buildCouplingGraph(internalRawCoupling);
  } catch (error) {
    console.warn(`[warn] buildCouplingGraph(internal) fallo: ${error?.message || error}`);
    internalGraph = {};
  }

  const denominator = Math.max(packages.length - 1, 1);
  const writer = createCsvWriter(args.output, OUTPUT_HEADERS);

  let processed = 0;
  for (const pkg of packages) {
    const warnings = packageWarnings.get(pkg.package) || [];

    const row = {
      package: pkg.package,
      version: pkg.version,
      size_bytes: pkg.size_bytes,
      file_count: pkg.file_count,
      nonempty_file_count: pkg.nonempty_file_count,
      jt_afferent: 0,
      jt_efferent_total: 0,
      jt_efferent_internal: 0,
      jt_efferent_external: 0,
      jt_instability: 0,
      jt_in_degree: 0,
      jt_out_degree: 0,
      jt_in_degree_centrality: 0,
      jt_out_degree_centrality: 0,
      jt_total_degree_centrality: 0,
      jt_dependency_score: 0,
      jt_warning_count: 0,
      jt_warning_messages: "",
    };

    try {
      let instabilityResult = null;
      try {
        const node = fullGraph[pkg.package] || { fanIn: [], fanOut: [] };
        instabilityResult = computeImportInstability(node);
        row.jt_afferent = instabilityResult.afferent;
        row.jt_efferent_total = instabilityResult.efferent;
        row.jt_instability = instabilityResult.instability;
      } catch (error) {
        warnMetric(pkg.package, "import_instability", error, warnings);
      }

      try {
        const internalNode = internalGraph[pkg.package] || { fanIn: [], fanOut: [] };
        const centrality = computeDependencyCentrality(internalNode, denominator);
        row.jt_in_degree = centrality.inDegree;
        row.jt_out_degree = centrality.outDegree;
        row.jt_in_degree_centrality = centrality.inDegreeCentrality;
        row.jt_out_degree_centrality = centrality.outDegreeCentrality;
        row.jt_total_degree_centrality = centrality.totalDegreeCentrality;
        row.jt_efferent_internal = centrality.outDegree;
      } catch (error) {
        warnMetric(pkg.package, "dependency_centrality", error, warnings);
      }

      try {
        row.jt_efferent_external = Math.max(0, row.jt_efferent_total - row.jt_efferent_internal);
      } catch (error) {
        warnMetric(pkg.package, "efferent_split", error, warnings);
      }

      try {
        const summary = computePackageDependencySummary(row.jt_afferent, row.jt_efferent_total);
        row.jt_dependency_score = summary.dependencyScore;
      } catch (error) {
        warnMetric(pkg.package, "dependency_summary", error, warnings);
      }

      row.jt_warning_count = warnings.length;
      row.jt_warning_messages = warnings.join(" | ");
      writer.writeRow(row);
    } catch (error) {
      warnMetric(pkg.package, "package_loop", error, warnings);
      row.jt_warning_count = warnings.length;
      row.jt_warning_messages = warnings.join(" | ");
      writer.writeRow(row);
    }

    processed += 1;
    if (processed % 500 === 0 || processed === packages.length) {
      console.log(`[jtmetrics] Progreso ${processed}/${packages.length}`);
    }
  }

  await writer.close();

  const elapsedSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);
  console.log(`[jtmetrics] Salida: ${args.output}`);
  console.log(`[jtmetrics] Finalizado en ${elapsedSeconds}s`);
}

run().catch((error) => {
  console.error(`[error] ${error?.message || error}`);
  process.exitCode = 1;
});
