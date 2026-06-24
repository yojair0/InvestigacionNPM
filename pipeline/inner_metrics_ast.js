const fs = require('fs');
const path = require('path');
const https = require('https');
const zlib = require('zlib');
const tar = require('tar-stream');

let babelParser = null;
let babelTraverse = null;
try {
    babelParser = require('@babel/parser');
    const traverseModule = require('@babel/traverse');
    babelTraverse = traverseModule.default || traverseModule;
} catch (error) {
    babelParser = null;
    babelTraverse = null;
}

const { buildCouplingGraph } = require('./jtmetrics/pure_metrics');

const DIR_METRICS = path.join(__dirname, '..', 'data', 'metrics');
const FILE_INPUT = path.join(DIR_METRICS, '05_final_ranking_msr.csv');
const FILE_OUTPUT = path.join(DIR_METRICS, '06_inner_metrics_ast.csv');

const OUTPUT_HEADERS = [
    'package',
    'version',
    'jt_ca',
    'jt_ce',
    'jt_instability',
    'module_file_count',
    'module_decl_mean',
    'module_decl_median',
    'module_decl_std_dev',
    'module_decl_max',
    'module_decl_outlier_count',
    'module_internal_fan_in_mean',
    'module_internal_fan_in_median',
    'module_internal_fan_in_std_dev',
    'module_internal_fan_in_max',
    'module_internal_fan_in_outlier_count',
    'module_internal_fan_out_mean',
    'module_internal_fan_out_median',
    'module_internal_fan_out_std_dev',
    'module_internal_fan_out_max',
    'module_internal_fan_out_outlier_count',
    'class_mean',
    'class_median',
    'class_std_dev',
    'class_max',
    'class_outlier_count',
    'function_mean',
    'function_median',
    'function_std_dev',
    'function_max',
    'function_outlier_count',
    'function_call_mean',
    'function_call_median',
    'function_call_std_dev',
    'function_call_max',
    'function_call_outlier_count'
];

const MAX_PACKAGES_TO_PROCESS = 500;
const SOURCE_EXTENSIONS = new Set(['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs']);

function csvEscape(value) {
    const text = value === null || value === undefined ? '' : String(value);
    if (/[",\n\r]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function createCsvRow(values) {
    return values.map(csvEscape).join(',') + '\n';
}

function parseCsvLine(line) {
    const values = [];
    let current = '';
    let inQuotes = false;

    for (let index = 0; index < line.length; index += 1) {
        const char = line[index];
        const next = line[index + 1];

        if (char === '"') {
            if (inQuotes && next === '"') {
                current += '"';
                index += 1;
            } else {
                inQuotes = !inQuotes;
            }
            continue;
        }

        if (char === ',' && !inQuotes) {
            values.push(current);
            current = '';
            continue;
        }

        current += char;
    }

    values.push(current);
    return values;
}

function readCsvRows(filePath) {
    const raw = fs.readFileSync(filePath, 'utf-8').replace(/^\uFEFF/, '').trim();
    if (!raw) {
        return { headers: [], rows: [] };
    }

    const lines = raw.split(/\r?\n/).filter((line) => line.trim().length > 0);
    const headers = parseCsvLine(lines.shift()).map((header) => header.trim());
    const rows = lines.map((line) => {
        const columns = parseCsvLine(line);
        const row = {};
        headers.forEach((header, index) => {
            row[header] = (columns[index] || '').trim();
        });
        return row;
    });

    return { headers, rows };
}

function parseIntSafe(value) {
    const parsed = Number.parseInt(String(value ?? '0'), 10);
    return Number.isFinite(parsed) ? parsed : 0;
}

function calcStats(numbers) {
    const values = Array.isArray(numbers)
        ? numbers.filter((value) => Number.isFinite(value)).slice()
        : [];

    if (values.length === 0) {
        return { mean: '0.00', median: '0.00', stdDev: '0.00', max: 0, outliersCount: 0 };
    }

    values.sort((a, b) => a - b);
    const sum = values.reduce((accumulator, value) => accumulator + value, 0);
    const mean = sum / values.length;
    const mid = Math.floor(values.length / 2);
    const median = values.length % 2 !== 0 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
    const squareDiffs = values.map((value) => Math.pow(value - mean, 2));
    const avgSquareDiff = squareDiffs.reduce((accumulator, value) => accumulator + value, 0) / values.length;
    const stdDev = Math.sqrt(avgSquareDiff);
    const threshold = mean + (3 * stdDev);
    const max = values[values.length - 1];
    const outliersCount = values.filter((value) => value > threshold && value > 0).length;

    return {
        mean: mean.toFixed(2),
        median: median.toFixed(2),
        stdDev: stdDev.toFixed(2),
        max,
        outliersCount
    };
}

function isAstNode(value) {
    return Boolean(value) && typeof value === 'object' && typeof value.type === 'string';
}

function getChildNodes(node) {
    const children = [];
    const ignoredKeys = new Set(['type', 'start', 'end', 'loc', 'range', 'extra', 'leadingComments', 'innerComments', 'trailingComments']);

    for (const key of Object.keys(node)) {
        if (ignoredKeys.has(key)) continue;
        const value = node[key];
        if (Array.isArray(value)) {
            for (const item of value) {
                if (isAstNode(item)) {
                    children.push(item);
                }
            }
            continue;
        }
        if (isAstNode(value)) {
            children.push(value);
        }
    }

    return children;
}

function isFunctionNode(node) {
    return node && (node.type === 'FunctionDeclaration' || node.type === 'FunctionExpression' || node.type === 'ArrowFunctionExpression');
}

function isClassNode(node) {
    return node && (node.type === 'ClassDeclaration' || node.type === 'ClassExpression');
}

function getStaticStringValue(node) {
    if (!node) return null;
    if ((node.type === 'StringLiteral' || node.type === 'Literal') && typeof node.value === 'string') {
        return node.value;
    }
    return null;
}

function normalizeTarEntryName(entryName) {
    if (!entryName) return '';
    let normalized = entryName.replace(/^\.\/+/, '');
    if (normalized.startsWith('package/')) {
        normalized = normalized.slice('package/'.length);
    }
    return path.posix.normalize(normalized).replace(/^\.(\/|$)/, '');
}

function isSourceFile(filePath) {
    return SOURCE_EXTENSIONS.has(path.posix.extname(filePath).toLowerCase());
}

function parsePackageJson(text) {
    if (!text || text.trim().length === 0) {
        return {};
    }

    try {
        return JSON.parse(text);
    } catch (error) {
        return {};
    }
}

function normalizeDependencySections(packageJson) {
    const sections = ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'];
    const dependencyNames = new Set();

    for (const section of sections) {
        const dependencies = packageJson && typeof packageJson === 'object' ? packageJson[section] : null;
        if (!dependencies || typeof dependencies !== 'object') continue;
        for (const name of Object.keys(dependencies)) {
            if (typeof name === 'string' && name.length > 0) {
                dependencyNames.add(name);
            }
        }
    }

    return dependencyNames;
}

function resolveInternalTarget(fromFilePath, specifier, availableFiles) {
    if (typeof specifier !== 'string' || specifier.length === 0) return null;
    if (!specifier.startsWith('.') && !specifier.startsWith('/')) return null;

    const fromDirectory = path.posix.dirname(fromFilePath);
    const joined = specifier.startsWith('/')
        ? path.posix.normalize(specifier)
        : path.posix.normalize(path.posix.join(fromDirectory, specifier));
    const basePath = joined.replace(/\.(js|jsx|ts|tsx|mjs|cjs)$/i, '');
    const candidates = new Set([
        joined,
        `${basePath}.js`,
        `${basePath}.jsx`,
        `${basePath}.ts`,
        `${basePath}.tsx`,
        `${basePath}.mjs`,
        `${basePath}.cjs`,
        `${basePath}/index.js`,
        `${basePath}/index.jsx`,
        `${basePath}/index.ts`,
        `${basePath}/index.tsx`,
        `${basePath}/index.mjs`,
        `${basePath}/index.cjs`
    ]);

    for (const candidate of candidates) {
        const normalized = path.posix.normalize(candidate);
        if (availableFiles.has(normalized)) {
            return normalized;
        }
    }

    return null;
}

function getBabelToolkit() {
    if (!babelParser || !babelTraverse) {
        throw new Error('Faltan las dependencias @babel/parser y @babel/traverse.');
    }

    return { parser: babelParser, traverse: babelTraverse };
}

function parseSourceCode(code) {
    const { parser } = getBabelToolkit();
    return parser.parse(code, {
        sourceType: 'unambiguous',
        errorRecovery: true,
        plugins: ['typescript', 'jsx']
    });
}

function countCallsWithinBabelFunction(functionPath) {
    let callCount = 0;

    functionPath.traverse({
        CallExpression() {
            callCount += 1;
        },
        Function(innerPath) {
            if (innerPath.node !== functionPath.node) {
                innerPath.skip();
            }
        },
        Class(innerPath) {
            if (innerPath.node !== functionPath.node) {
                innerPath.skip();
            }
        }
    });

    return callCount;
}

function collectAstMetrics(code) {
    const { traverse } = getBabelToolkit();
    const ast = parseSourceCode(code);

    const moduleSpecifiers = [];
    let classCount = 0;
    let functionCount = 0;
    const functionCallCounts = [];

    traverse(ast, {
        ImportDeclaration(pathNode) {
            const specifier = pathNode.node?.source?.value;
            if (typeof specifier === 'string' && specifier.length > 0) {
                moduleSpecifiers.push(specifier);
            }
        },
        CallExpression(pathNode) {
            const callee = pathNode.node?.callee;
            const firstArgument = pathNode.node?.arguments?.[0];
            const stringValue = getStaticStringValue(firstArgument);
            if (callee && callee.type === 'Identifier' && callee.name === 'require' && typeof stringValue === 'string') {
                moduleSpecifiers.push(stringValue);
            }
        },
        ClassDeclaration() {
            classCount += 1;
        },
        FunctionDeclaration(pathNode) {
            functionCount += 1;
            functionCallCounts.push(countCallsWithinBabelFunction(pathNode));
        },
        FunctionExpression(pathNode) {
            functionCount += 1;
            functionCallCounts.push(countCallsWithinBabelFunction(pathNode));
        },
        ArrowFunctionExpression(pathNode) {
            functionCount += 1;
            functionCallCounts.push(countCallsWithinBabelFunction(pathNode));
        }
    });

    return {
        moduleDeclarationCount: moduleSpecifiers.length,
        moduleSpecifiers,
        classCount,
        functionCount,
        functionCallCounts
    };
}

function createEmptyMetrics(pkgName, version, ca) {
    return {
        package: pkgName,
        version: version || 'latest',
        jt_ca: ca,
        jt_ce: 0,
        jt_instability: 0,
        module_file_count: 0,
        module_decl_mean: '0.00',
        module_decl_median: '0.00',
        module_decl_std_dev: '0.00',
        module_decl_max: 0,
        module_decl_outlier_count: 0,
        module_internal_fan_in_mean: '0.00',
        module_internal_fan_in_median: '0.00',
        module_internal_fan_in_std_dev: '0.00',
        module_internal_fan_in_max: 0,
        module_internal_fan_in_outlier_count: 0,
        module_internal_fan_out_mean: '0.00',
        module_internal_fan_out_median: '0.00',
        module_internal_fan_out_std_dev: '0.00',
        module_internal_fan_out_max: 0,
        module_internal_fan_out_outlier_count: 0,
        class_mean: '0.00',
        class_median: '0.00',
        class_std_dev: '0.00',
        class_max: 0,
        class_outlier_count: 0,
        function_mean: '0.00',
        function_median: '0.00',
        function_std_dev: '0.00',
        function_max: 0,
        function_outlier_count: 0,
        function_call_mean: '0.00',
        function_call_median: '0.00',
        function_call_std_dev: '0.00',
        function_call_max: 0,
        function_call_outlier_count: 0
    };
}

function finalizePackageMetrics(pkgName, version, ca, packageJsonText, sourceRecords) {
    const packageJson = parsePackageJson(packageJsonText);
    const ce = normalizeDependencySections(packageJson).size;
    const instability = ca + ce === 0 ? 0 : Number((ce / (ca + ce)).toFixed(4));

    const availableFiles = new Set(sourceRecords.map((record) => record.filePath));
    const rawCoupling = {};

    for (const record of sourceRecords) {
        const internalTargets = new Set();
        for (const specifier of record.moduleSpecifiers) {
            const resolved = resolveInternalTarget(record.filePath, specifier, availableFiles);
            if (resolved) {
                internalTargets.add(resolved);
            }
        }
        rawCoupling[record.filePath] = Array.from(internalTargets);
    }

    let couplingGraph = {};
    try {
        couplingGraph = buildCouplingGraph(rawCoupling);
    } catch (error) {
        couplingGraph = {};
    }

    const moduleDeclCounts = sourceRecords.map((record) => record.moduleDeclarationCount);
    const moduleFanInCounts = sourceRecords.map((record) => {
        const node = couplingGraph[record.filePath] || { fanIn: [], fanOut: [] };
        return Array.isArray(node.fanIn) ? node.fanIn.length : 0;
    });
    const moduleFanOutCounts = sourceRecords.map((record) => {
        const node = couplingGraph[record.filePath] || { fanIn: [], fanOut: [] };
        return Array.isArray(node.fanOut) ? node.fanOut.length : 0;
    });
    const classCounts = sourceRecords.map((record) => record.classCount);
    const functionCounts = sourceRecords.map((record) => record.functionCount);
    const functionCallCounts = [];

    for (const record of sourceRecords) {
        functionCallCounts.push(...record.functionCallCounts);
    }

    const moduleDeclStats = calcStats(moduleDeclCounts);
    const moduleFanInStats = calcStats(moduleFanInCounts);
    const moduleFanOutStats = calcStats(moduleFanOutCounts);
    const classStats = calcStats(classCounts);
    const functionStats = calcStats(functionCounts);
    const functionCallStats = calcStats(functionCallCounts);

    return {
        package: pkgName,
        version: version || packageJson.version || 'latest',
        jt_ca: ca,
        jt_ce: ce,
        jt_instability: instability,
        module_file_count: sourceRecords.length,
        module_decl_mean: moduleDeclStats.mean,
        module_decl_median: moduleDeclStats.median,
        module_decl_std_dev: moduleDeclStats.stdDev,
        module_decl_max: moduleDeclStats.max,
        module_decl_outlier_count: moduleDeclStats.outliersCount,
        module_internal_fan_in_mean: moduleFanInStats.mean,
        module_internal_fan_in_median: moduleFanInStats.median,
        module_internal_fan_in_std_dev: moduleFanInStats.stdDev,
        module_internal_fan_in_max: moduleFanInStats.max,
        module_internal_fan_in_outlier_count: moduleFanInStats.outliersCount,
        module_internal_fan_out_mean: moduleFanOutStats.mean,
        module_internal_fan_out_median: moduleFanOutStats.median,
        module_internal_fan_out_std_dev: moduleFanOutStats.stdDev,
        module_internal_fan_out_max: moduleFanOutStats.max,
        module_internal_fan_out_outlier_count: moduleFanOutStats.outliersCount,
        class_mean: classStats.mean,
        class_median: classStats.median,
        class_std_dev: classStats.stdDev,
        class_max: classStats.max,
        class_outlier_count: classStats.outliersCount,
        function_mean: functionStats.mean,
        function_median: functionStats.median,
        function_std_dev: functionStats.stdDev,
        function_max: functionStats.max,
        function_outlier_count: functionStats.outliersCount,
        function_call_mean: functionCallStats.mean,
        function_call_median: functionCallStats.median,
        function_call_std_dev: functionCallStats.stdDev,
        function_call_max: functionCallStats.max,
        function_call_outlier_count: functionCallStats.outliersCount
    };
}

async function analyzeTarball(pkgName, version, ca) {
    const safeVersion = version && version.length > 0 ? version : 'latest';
    const tarballName = pkgName.split('/').pop();
    const url = `https://registry.npmjs.org/${pkgName}/-/${tarballName}-${safeVersion}.tgz`;

    return new Promise((resolve) => {
        const sourceRecords = [];
        let packageJsonText = '';
        let packageJsonPath = '';
        let pendingEntries = 0;
        let tarFinished = false;
        let settled = false;

        function finishIfReady() {
            if (!tarFinished || pendingEntries !== 0 || settled) {
                return;
            }

            settled = true;
            resolve(finalizePackageMetrics(pkgName, safeVersion, ca, packageJsonText, sourceRecords));
        }

        function failSoft() {
            if (settled) return;
            settled = true;
            resolve(createEmptyMetrics(pkgName, safeVersion, ca));
        }

        const request = https.get(url, (response) => {
            if (response.statusCode !== 200) {
                response.resume();
                failSoft();
                return;
            }

            const extract = tar.extract();

            extract.on('entry', (header, stream, next) => {
                pendingEntries += 1;
                const entryName = normalizeTarEntryName(header?.name || '');
                const isPackageJson = path.posix.basename(entryName) === 'package.json';
                const isSource = isSourceFile(entryName);
                let text = '';

                function completeEntry() {
                    pendingEntries -= 1;
                    next();
                    finishIfReady();
                }

                if (!isPackageJson && !isSource) {
                    stream.resume();
                    stream.on('end', completeEntry);
                    return;
                }

                stream.on('data', (chunk) => {
                    text += chunk.toString('utf-8');
                });

                stream.on('end', () => {
                    try {
                        if (isPackageJson) {
                            if (!packageJsonPath || entryName.length < packageJsonPath.length) {
                                packageJsonPath = entryName;
                                packageJsonText = text;
                            }
                        } else if (isSource) {
                            try {
                                const metrics = collectAstMetrics(text);
                                sourceRecords.push({
                                    filePath: entryName,
                                    moduleDeclarationCount: metrics.moduleDeclarationCount,
                                    moduleSpecifiers: metrics.moduleSpecifiers,
                                    classCount: metrics.classCount,
                                    functionCount: metrics.functionCount,
                                    functionCallCounts: metrics.functionCallCounts
                                });
                            } catch (error) {
                                sourceRecords.push({
                                    filePath: entryName,
                                    moduleDeclarationCount: 0,
                                    moduleSpecifiers: [],
                                    classCount: 0,
                                    functionCount: 0,
                                    functionCallCounts: []
                                });
                            }
                        }
                    } finally {
                        completeEntry();
                    }
                });

                stream.on('error', () => {
                    if (isSource) {
                        sourceRecords.push({
                            filePath: entryName,
                            moduleDeclarationCount: 0,
                            moduleSpecifiers: [],
                            classCount: 0,
                            functionCount: 0,
                            functionCallCounts: []
                        });
                    }
                    completeEntry();
                });
            });

            extract.on('finish', () => {
                tarFinished = true;
                finishIfReady();
            });

            extract.on('error', () => {
                failSoft();
            });

            const gunzip = zlib.createGunzip();
            gunzip.on('error', () => {
                failSoft();
            });

            response.on('error', () => {
                failSoft();
            });

            response.pipe(gunzip).pipe(extract);
        });

        request.on('error', () => {
            failSoft();
        });
    });
}

function ensureOutputHeader(headers) {
    const expected = headers.join(',');

    if (!fs.existsSync(FILE_OUTPUT)) {
        fs.writeFileSync(FILE_OUTPUT, `${expected}\n`, 'utf-8');
        return;
    }

    const existing = fs.readFileSync(FILE_OUTPUT, 'utf-8').replace(/^\uFEFF/, '').trim();
    if (!existing) {
        fs.writeFileSync(FILE_OUTPUT, `${expected}\n`, 'utf-8');
        return;
    }

    const firstLine = existing.split(/\r?\n/)[0];
    if (firstLine !== expected) {
        fs.writeFileSync(FILE_OUTPUT, `${expected}\n`, 'utf-8');
    }
}

async function run() {
    console.log('--- Iniciando Fase AST Unificada (Outer + Inner) ---');

    if (!babelParser || !babelTraverse) {
        console.error('Faltan las dependencias @babel/parser y @babel/traverse.');
        console.error('Instálalas para habilitar el soporte TS/JSX requerido.');
        return;
    }

    if (!fs.existsSync(FILE_INPUT)) {
        console.error('No se encontró el CSV consolidado.');
        return;
    }

    const { headers, rows } = readCsvRows(FILE_INPUT);
    const targets = rows.slice(0, MAX_PACKAGES_TO_PROCESS);
    const pkgIndex = headers.indexOf('package');
    const verIndex = headers.indexOf('version');
    const caIndex = headers.indexOf('fan_in_global') >= 0
        ? headers.indexOf('fan_in_global')
        : headers.indexOf('jt_afferent');

    if (pkgIndex < 0) {
        console.error('El CSV de entrada no contiene la columna package.');
        return;
    }

    ensureOutputHeader(OUTPUT_HEADERS);

    const envStart = process.env.START_INDEX || process.argv[2];
    let startIndex = 0;
    if (envStart) {
        const parsed = Number.parseInt(envStart, 10);
        if (Number.isFinite(parsed) && parsed >= 0) {
            startIndex = parsed;
        }
    }

    console.log(`Procesando ${targets.length} paquetes locales (límite interno: ${MAX_PACKAGES_TO_PROCESS}).`);
    console.log(`Reanudar desde índice: ${startIndex} (0-based dentro del listado local)`);

    for (let index = startIndex; index < targets.length; index += 1) {
        const row = targets[index];
        const pkgName = (row[headers[pkgIndex]] || '').trim();
        const version = verIndex >= 0 ? (row[headers[verIndex]] || '').trim() : '';
        const ca = caIndex >= 0 ? parseIntSafe(row[headers[caIndex]]) : 0;

        if (!pkgName) {
            continue;
        }

        if (index % 10 === 0) {
            console.log(`Procesando ${index}/${targets.length}... (${pkgName})`);
        }

        const result = await analyzeTarball(pkgName, version, ca);
        fs.appendFileSync(FILE_OUTPUT, createCsvRow([
            result.package,
            result.version,
            result.jt_ca,
            result.jt_ce,
            result.jt_instability,
            result.module_file_count,
            result.module_decl_mean,
            result.module_decl_median,
            result.module_decl_std_dev,
            result.module_decl_max,
            result.module_decl_outlier_count,
            result.module_internal_fan_in_mean,
            result.module_internal_fan_in_median,
            result.module_internal_fan_in_std_dev,
            result.module_internal_fan_in_max,
            result.module_internal_fan_in_outlier_count,
            result.module_internal_fan_out_mean,
            result.module_internal_fan_out_median,
            result.module_internal_fan_out_std_dev,
            result.module_internal_fan_out_max,
            result.module_internal_fan_out_outlier_count,
            result.class_mean,
            result.class_median,
            result.class_std_dev,
            result.class_max,
            result.class_outlier_count,
            result.function_mean,
            result.function_median,
            result.function_std_dev,
            result.function_max,
            result.function_outlier_count,
            result.function_call_mean,
            result.function_call_median,
            result.function_call_std_dev,
            result.function_call_max,
            result.function_call_outlier_count
        ]), 'utf-8');
    }

    console.log('\n--- Análisis AST Finalizado Completamente ---');
    console.log(`Guardado en: ${FILE_OUTPUT}`);
}

run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});