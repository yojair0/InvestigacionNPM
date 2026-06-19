"use strict";

/**
 * Port de funciones puras de JTMetrics (vtjmetrics) adaptadas a nivel paquete.
 * Fuente conceptual:
 * - importInstability.metric.js
 * - dependencyCentrality.metric.js
 */

function roundTo4(value) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Number(value.toFixed(4));
}

/**
 * Replica el armado de grafo de acoplamiento del repositorio original.
 * @param {Record<string, string[]>} rawCoupling
 * @returns {Record<string, {fanOut: string[], fanIn: string[]}>}
 */
function buildCouplingGraph(rawCoupling) {
  const graph = {};
  const fanInMap = {};

  for (const [nodeId, fanOut] of Object.entries(rawCoupling || {})) {
    graph[nodeId] = Array.isArray(fanOut)
      ? Array.from(new Set(fanOut.filter((dep) => typeof dep === "string" && dep.length > 0)))
      : [];
    fanInMap[nodeId] = fanInMap[nodeId] || [];
  }

  for (const [nodeId, fanOut] of Object.entries(graph)) {
    for (const dep of fanOut) {
      if (!graph[dep]) {
        graph[dep] = [];
      }
      if (!fanInMap[dep]) {
        fanInMap[dep] = [];
      }
      fanInMap[dep].push(nodeId);
    }
  }

  for (const nodeId of Object.keys(fanInMap)) {
    fanInMap[nodeId] = Array.from(new Set(fanInMap[nodeId]));
  }

  const result = {};
  for (const nodeId of Object.keys(graph)) {
    result[nodeId] = {
      fanOut: graph[nodeId],
      fanIn: fanInMap[nodeId] || [],
    };
  }

  return result;
}

/**
 * Adaptacion de importInstability.metric.js para un nodo del grafo.
 * I = Ce / (Ca + Ce)
 */
function computeImportInstability(couplingNode) {
  const afferent = Array.isArray(couplingNode?.fanIn) ? couplingNode.fanIn.length : 0;
  const efferent = Array.isArray(couplingNode?.fanOut) ? couplingNode.fanOut.length : 0;
  const instability = afferent + efferent === 0 ? 0 : roundTo4(efferent / (afferent + efferent));
  return {
    afferent,
    efferent,
    instability,
  };
}

/**
 * Adaptacion de dependencyCentrality.metric.js para un nodo del grafo.
 */
function computeDependencyCentrality(couplingNode, denominator) {
  const safeDenominator = Math.max(Number(denominator) || 1, 1);
  const inDegree = Array.isArray(couplingNode?.fanIn) ? couplingNode.fanIn.length : 0;
  const outDegree = Array.isArray(couplingNode?.fanOut) ? couplingNode.fanOut.length : 0;

  return {
    inDegree,
    outDegree,
    inDegreeCentrality: roundTo4(inDegree / safeDenominator),
    outDegreeCentrality: roundTo4(outDegree / safeDenominator),
    totalDegreeCentrality: roundTo4((inDegree + outDegree) / (2 * safeDenominator)),
  };
}

/**
 * Adaptacion de summaries (class/function dependency summary) a nivel paquete.
 */
function computePackageDependencySummary(afferent, efferent) {
  const fanInPackages = Math.max(0, Number(afferent) || 0);
  const fanOutPackages = Math.max(0, Number(efferent) || 0);
  return {
    fanInPackages,
    fanOutPackages,
    dependencyScore: fanInPackages + fanOutPackages,
  };
}

module.exports = {
  roundTo4,
  buildCouplingGraph,
  computeImportInstability,
  computeDependencyCentrality,
  computePackageDependencySummary,
};
