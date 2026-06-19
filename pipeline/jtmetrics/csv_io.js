"use strict";

const fs = require("fs");
const readline = require("readline");

function parseCsvLine(line) {
  const values = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = i + 1 < line.length ? line[i + 1] : "";

    if (char === '"') {
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      values.push(current);
      current = "";
      continue;
    }

    current += char;
  }

  values.push(current);
  return values;
}

function toCsvValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  const text = String(value);
  if (text.includes('"') || text.includes(",") || text.includes("\n") || text.includes("\r")) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function rowToCsv(row, headers) {
  return headers.map((h) => toCsvValue(row[h])).join(",");
}

/**
 * Lee CSV via stream y soporta campos multilínea entre comillas.
 */
async function readCsvRows(filePath, onRow) {
  const input = fs.createReadStream(filePath, { encoding: "utf8" });
  const rl = readline.createInterface({ input, crlfDelay: Infinity });

  let headers = null;
  let pending = "";

  for await (const rawLine of rl) {
    const line = pending ? `${pending}\n${rawLine}` : rawLine;
    const quoteCount = (line.match(/"/g) || []).length;

    if (quoteCount % 2 !== 0) {
      pending = line;
      continue;
    }

    pending = "";
    const normalized = line.endsWith("\r") ? line.slice(0, -1) : line;
    if (!headers) {
      headers = parseCsvLine(normalized).map((h) => h.trim());
      continue;
    }

    if (normalized.trim() === "") {
      continue;
    }

    const values = parseCsvLine(normalized);
    const row = {};
    for (let i = 0; i < headers.length; i += 1) {
      row[headers[i]] = values[i] !== undefined ? values[i] : "";
    }

    await onRow(row);
  }

  if (pending) {
    throw new Error("CSV invalido: campo con comillas no cerradas.");
  }

  if (!headers) {
    throw new Error("CSV vacio o sin encabezados.");
  }

  return headers;
}

function createCsvWriter(filePath, headers) {
  const output = fs.createWriteStream(filePath, { encoding: "utf8" });
  output.write(`${headers.map((h) => toCsvValue(h)).join(",")}\n`);

  return {
    writeRow(row) {
      output.write(`${rowToCsv(row, headers)}\n`);
    },
    async close() {
      await new Promise((resolve, reject) => {
        output.end(() => resolve());
        output.on("error", reject);
      });
    },
  };
}

module.exports = {
  readCsvRows,
  createCsvWriter,
};
