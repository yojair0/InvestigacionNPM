const fs = require('fs');
const path = require('path');
const https = require('https');
const zlib = require('zlib');
const tar = require('tar-stream');
const acorn = require('acorn');

const DIR_METRICS = path.join(__dirname, '..', 'data', 'metrics');
const FILE_INPUT = path.join(DIR_METRICS, '05_final_ranking_msr.csv');
const FILE_OUTPUT = path.join(DIR_METRICS, '06_inner_metrics_ast.csv');

// --- Matemáticas Estadísticas Básicas ---
function calcStats(numbers) {
    if (numbers.length === 0) return { mean: 0, median: 0, stdDev: 0, max: 0, outliers: 0 };
    numbers.sort((a, b) => a - b);
    
    const sum = numbers.reduce((a, b) => a + b, 0);
    const mean = sum / numbers.length;
    
    // Mediana
    const mid = Math.floor(numbers.length / 2);
    const median = numbers.length % 2 !== 0 ? numbers[mid] : (numbers[mid - 1] + numbers[mid]) / 2;
    
    // Desviación Estándar
    const squareDiffs = numbers.map(value => Math.pow(value - mean, 2));
    const avgSquareDiff = squareDiffs.reduce((a, b) => a + b, 0) / numbers.length;
    const stdDev = Math.sqrt(avgSquareDiff);
    
    // Outliers (Usando el método de 3 desviaciones estándar o z-score simple)
    const threshold = mean + (3 * stdDev);
    const max = numbers[numbers.length - 1];
    const outliersCount = numbers.filter(n => n > threshold && n > 0).length;
    
    return { mean: mean.toFixed(2), median, stdDev: stdDev.toFixed(2), max, outliersCount };
}

// --- Descarga Segura y Análisis en RAM ---
async function analyzeTarball(pkgName, version) {
    if (!version) version = 'latest';
    // Construir la URL del registro NPM oficial (el TGZ real, nada de scripts)
    const url = `https://registry.npmjs.org/${pkgName}/-/${pkgName.split('/').pop()}-${version}.tgz`;
    
    return new Promise((resolve) => {
        let functionCount = 0;
        let functionCalls = []; // Guardará cuántas veces llama a otra cosa (Inner Fan-Out) cada función encontrada

        https.get(url, (response) => {
            if (response.statusCode !== 200) {
                // Falla de red, paquete no existe o versión mala. Saltamos tolerando el fallo.
                return resolve(null);
            }

            const extract = tar.extract();

            extract.on('entry', (header, stream, next) => {
                // Solo leemos archivos .js 
                if (header.name.endsWith('.js')) {
                    let code = '';
                    stream.on('data', (chunk) => code += chunk);
                    stream.on('end', () => {
                        try {
                            // "acorn.parse"  Lee la gramática del código.
                            // Tolerar errores de parseo por si usan sintaxis súper moderna o rota.
                            const ast = acorn.parse(code, { ecmaVersion: 2022, sourceType: 'module' });
                            
                            // Un simple "caminante" recursivo (Visitor) del AST para buscar funciones
                            function walkAST(node) {
                                if (!node) return;
                                
                                // Si es una declaración de función o una "arrow function"
                                if (node.type === 'FunctionDeclaration' || node.type === 'FunctionExpression' || node.type === 'ArrowFunctionExpression') {
                                    functionCount++;
                                    let internalCalls = 0;
                                    
                                    // Buscar cuántos "CallExpression" (llamadas a otras funciones) hay DENTRO de esta función
                                    function innerWalk(childNode) {
                                        if(!childNode) return;
                                        if (childNode.type === 'CallExpression') internalCalls++;
                                        for (const key in childNode) {
                                            if (childNode[key] && typeof childNode[key] === 'object') {
                                                innerWalk(childNode[key]);
                                            }
                                        }
                                    }
                                    innerWalk(node.body);
                                    functionCalls.push(internalCalls);
                                }
                                
                                // Seguir caminando el árbol principal
                                for (const key in node) {
                                    if (node[key] && typeof node[key] === 'object') {
                                        walkAST(node[key]);
                                    }
                                }
                            }
                            
                            walkAST(ast);
                        } catch (err) {
                            // Achivo ilegible (ej. TypeScript mezclado o JSX loco). Fallo tolerado.
                        }
                        next();
                    });
                } else {
                    // Si no es JS (fotos, readmes), descartar en memoria de inmediato
                    stream.resume();
                    next();
                }
            });

            extract.on('finish', () => {
                // Terminó de leer todo el paquete
                const stats = calcStats(functionCalls);
                resolve({
                    pkgName,
                    total_functions: functionCount,
                    inner_mean: stats.mean,
                    inner_median: stats.median,
                    inner_std_dev: stats.stdDev,
                    inner_max_calls: stats.max,
                    inner_outlier_count: stats.outliersCount
                });
            });

            // Conectar el flujo: Descarga de internet -> Descomprimir gzip -> Descomprimir Tar (en memoria pura)
            response.pipe(zlib.createGunzip()).pipe(extract);
        }).on('error', () => {
            resolve(null);
        });
    });
}

// --- Flujo Principal ---
async function run() {
    console.log('--- Iniciando Fase AST (Inner Metrics Seguras) ---');
    if (!fs.existsSync(FILE_INPUT)) {
        console.error('No se encontró el CSV consolidado.');
        return;
    }

    const lines = fs.readFileSync(FILE_INPUT, 'utf-8').trim().split('\n');
    const headers = lines[0].split(',');
    const pkgIndex = headers.indexOf('package');
    const verIndex = headers.indexOf('version');

    // Preparar el archivo de salida
    const outHeaders = ['package', 'total_functions', 'inner_mean', 'inner_median', 'inner_std_dev', 'inner_max_calls', 'inner_outlier_count'];

    // Procesar todos (LIMITADO SOLO A LOS 5000 / 4974 LOCALES)
    const targets = lines.slice(1);
    console.log(`Procesando ${targets.length} paquetes locales.`);

    // Soporte de reanudación (checkpoint): si el archivo de salida existe, contar filas ya procesadas
    let startIndex = 0;
    if (fs.existsSync(FILE_OUTPUT)) {
        try {
            const existing = fs.readFileSync(FILE_OUTPUT, 'utf-8').trim();
            if (existing.length > 0) {
                const existingLines = existing.split('\n');
                // Si el header está presente, restar 1
                if (existingLines[0].startsWith('package,')) {
                    startIndex = existingLines.length - 1;
                } else {
                    startIndex = existingLines.length;
                }
            }
        } catch (e) {
            startIndex = 0;
        }
    } else {
        // Si no existe el archivo, crear con cabecera
        fs.writeFileSync(FILE_OUTPUT, outHeaders.join(',') + '\n', 'utf-8');
    }

    // Permitir sobreescribir start por variable de entorno o argumento CLI (opcional)
    const envStart = process.env.START_INDEX || process.argv[2];
    if (envStart) {
        const parsed = parseInt(envStart, 10);
        if (!isNaN(parsed) && parsed >= 0) startIndex = parsed;
    }

    console.log(`Reanudar desde índice: ${startIndex} (0-based dentro del listado local)`);

    for (let i = startIndex; i < targets.length; i++) {
        const row = targets[i].split(',');
        const pkgName = row[pkgIndex];
        const version = row[verIndex];

        if (!pkgName) continue;

        // Progreso
        if (i % 10 === 0) console.log(`Procesando ${i}/${targets.length}... (${pkgName})`);

        // Llamar a internet para BAJAR EL FUENTE (Sin instalar y directo a RAM)
        const result = await analyzeTarball(pkgName, version);

        if (result && result.total_functions > 0) {
            const outRow = [
                result.pkgName,
                result.total_functions,
                result.inner_mean,
                result.inner_median,
                result.inner_std_dev,
                result.inner_max_calls,
                result.inner_outlier_count
            ];
            // Agregarlo al CSV instantáneamente para salvar progreso si se cae
            fs.appendFileSync(FILE_OUTPUT, outRow.join(',') + '\n', 'utf-8');
        } else {
            // Cero o Fallo: Lo anotamos con ceros para no perder el tracking
            fs.appendFileSync(FILE_OUTPUT, `${pkgName},0,0,0,0,0,0\n`, 'utf-8');
        }
    }

    console.log('\n--- Análisis AST Finalizado Completamente ---');
    console.log(`Guardado en: ${FILE_OUTPUT}`);
}

run().catch(console.error);