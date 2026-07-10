const fs = require('fs');
const readline = require('readline');
const path = require('path');

async function main() {
    console.log("--- Iniciando extracción de Métricas Extendidas (NDJSON a CSV) ---");
    
    const ndjsonPath = path.join(__dirname, '..', 'data', 'metrics', 'inner_metrics_jt.ndjson');
    const csvOutPath = path.join(__dirname, '..', 'data', 'metrics', 'inner_extended_metrics.csv');

    if (!fs.existsSync(ndjsonPath)) return;

    const fileStream = fs.createReadStream(ndjsonPath, { encoding: 'utf8' });
    const rl = readline.createInterface({ input: fileStream, crlfDelay: Infinity });
    const csvStream = fs.createWriteStream(csvOutPath, { flags: 'w' });

    const headers = [
        "package",
        "avg_dependency_centrality",
        "avg_lines_per_file",
        "avg_function_length",
        "avg_parameters_per_func"
    ];
    csvStream.write(headers.join(',') + '\n');

    const calcAvg = (arr) => arr.length ? (arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(4) : "0.0000";
    let processed = 0;

    for await (const line of rl) {
        if (!line.trim()) continue;
        processed++;

        try {
            const data = JSON.parse(line);
            const pkgName = data.package;
            if (!pkgName) continue;

            const metrics = data.metrics || {};

            // 1. Dependency Centrality
            const centrality = [];
            if (metrics['dependency-centrality']?.result) {
                for (const file in metrics['dependency-centrality'].result) {
                    centrality.push(metrics['dependency-centrality'].result[file].totalDegreeCentrality || 0);
                }
            }

            // 2. Lines per file (nonEmpty)
            const lines = [];
            if (metrics['lines-per-file']?.result) {
                for (const file in metrics['lines-per-file'].result) {
                    lines.push(metrics['lines-per-file'].result[file].nonEmpty || 0);
                }
            }

            // 3. Function Length & 4. Parameters
            const funcLen = [];
            const funcParams = [];
            if (metrics['function-length']?.result && metrics['parameter-count']?.result) {
                const lenRes = metrics['function-length'].result;
                const paramRes = metrics['parameter-count'].result;
                for (const file in lenRes) {
                    for (const func in lenRes[file]) {
                        funcLen.push(lenRes[file][func].lines || 0);
                        if (paramRes[file] && paramRes[file][func]) {
                            funcParams.push(paramRes[file][func].params || 0);
                        }
                    }
                }
            }

            const row = [
                pkgName,
                calcAvg(centrality), calcAvg(lines), calcAvg(funcLen), calcAvg(funcParams)
            ].join(',');

            csvStream.write(row + '\n');

        } catch (err) {}
        if (processed % 500 === 0) console.log(`[INFO] Procesados ${processed} paquetes...`);
    }

    csvStream.end();
    console.log(`\n CSV de métricas extendidas guardado en: ${csvOutPath}`);
}
main();