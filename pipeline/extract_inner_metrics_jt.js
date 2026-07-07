const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const zlib = require('zlib');
const tar = require('tar-stream');
const os = require('os');

const DIR_METRICS = path.join(__dirname, '..', 'data', 'metrics');
const FILE_INPUT = path.join(DIR_METRICS, 'packages_info.csv');
const FILE_OUTPUT = path.join(DIR_METRICS, 'inner_metrics_jt.ndjson');
const FILE_TRACKER = path.join(DIR_METRICS, 'inner_metrics_jt_progress.txt');
const TMP_DIR = path.join(__dirname, '..', 'tmp_extract');

const MAX_PACKAGES = 5000;

function parseCsvLine(line) {
    const fields = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
            if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
                current += '"';
                i++;
            } else {
                inQuotes = !inQuotes;
            }
        } else if (ch === ',' && !inQuotes) {
            fields.push(current);
            current = '';
        } else {
            current += ch;
        }
    }
    fields.push(current);
    return fields;
}

function readPackages() {
    const content = fs.readFileSync(FILE_INPUT, 'utf-8');
    const lines = content.split(/\r?\n/).filter(l => l.trim());
    const headers = parseCsvLine(lines[0]);
    const pkgIdx = headers.indexOf('package');
    const verIdx = headers.indexOf('version');

    const packages = [];
    for (let i = 1; i < lines.length && packages.length < MAX_PACKAGES; i++) {
        const fields = parseCsvLine(lines[i]);
        if (fields[pkgIdx]) {
            packages.push({ name: fields[pkgIdx], version: fields[verIdx] || 'latest' });
        }
    }
    return packages;
}

function getTarballUrl(packageName, version) {
    return new Promise((resolve, reject) => {
        const url = `https://registry.npmjs.org/${packageName}`;
        https.get(url, { headers: { 'Accept': 'application/json' } }, (res) => {
            if (res.statusCode === 404) return reject(new Error(`Package not found: ${packageName}`));
            if (res.statusCode !== 200) return reject(new Error(`Registry returned ${res.statusCode} for ${packageName}`));

            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const meta = JSON.parse(data);
                    const ver = meta.versions?.[version] || meta.versions?.[meta['dist-tags']?.latest];
                    if (!ver?.dist?.tarball) return reject(new Error(`No tarball found for ${packageName}@${version}`));
                    resolve(ver.dist.tarball);
                } catch (e) {
                    reject(new Error(`Failed to parse registry response for ${packageName}: ${e.message}`));
                }
            });
            res.on('error', reject);
        }).on('error', reject);
    });
}

function downloadAndExtract(tarballUrl, destDir) {
    return new Promise((resolve, reject) => {
        const protocol = tarballUrl.startsWith('https') ? https : http;
        protocol.get(tarballUrl, (res) => {
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                return downloadAndExtract(res.headers.location, destDir).then(resolve).catch(reject);
            }
            if (res.statusCode !== 200) return reject(new Error(`Download failed: ${res.statusCode}`));

            const extract = tar.extract();
            let fileCount = 0;

            extract.on('entry', (header, stream, next) => {
                try {
                    let filePath = header.name.replace(/^[^/]+\//, '');
                    filePath = filePath.replace(/[:<>"|?*]/g, '_');
                    const fullPath = path.join(destDir, filePath);

                    if (header.type === 'directory') {
                        fs.mkdirSync(fullPath, { recursive: true });
                        stream.resume();
                        next();
                    } else if (header.type === 'file') {
                        const dir = path.dirname(fullPath);
                        fs.mkdirSync(dir, { recursive: true });
                        const ws = fs.createWriteStream(fullPath);
                        stream.pipe(ws);
                        ws.on('finish', () => { fileCount++; next(); });
                        ws.on('error', () => { stream.resume(); next(); });
                    } else {
                        stream.resume();
                        next();
                    }
                } catch (e) {
                    stream.resume();
                    next();
                }
            });

            extract.on('finish', () => resolve(fileCount));
            extract.on('error', reject);

            res.pipe(zlib.createGunzip()).pipe(extract);
        }).on('error', reject);
    });
}

function rmDir(dir) {
    if (fs.existsSync(dir)) {
        fs.rmSync(dir, { recursive: true, force: true });
    }
}

const { fork } = require('child_process');
const WORKER_PATH = path.join(__dirname, 'jt_worker.js');
const WORKER_TIMEOUT_MS = 5 * 60 * 1000;
const WORKER_MAX_MEMORY = 8192;

function runJtmetricsIsolated(codePath) {
    return new Promise((resolve, reject) => {
        const child = fork(WORKER_PATH, [codePath], {
            execArgv: [`--max-old-space-size=${WORKER_MAX_MEMORY}`],
            silent: true
        });

        const timer = setTimeout(() => {
            child.kill('SIGKILL');
            reject(new Error('Timeout: analysis exceeded 5 minutes'));
        }, WORKER_TIMEOUT_MS);

        child.on('message', (msg) => {
            clearTimeout(timer);
            if (msg.success) {
                resolve(msg.metrics);
            } else {
                reject(new Error(msg.error || 'Worker failed'));
            }
        });

        child.on('error', (err) => {
            clearTimeout(timer);
            reject(err);
        });

        child.on('exit', (code, signal) => {
            clearTimeout(timer);
            if (code !== 0 && code !== null) {
                reject(new Error(`Worker crashed (code=${code}, signal=${signal}) - likely OOM`));
            }
        });
    });
}

function getProcessedPackages() {
    const processed = new Set();
    if (fs.existsSync(FILE_TRACKER)) {
        const lines = fs.readFileSync(FILE_TRACKER, 'utf-8').split(/\r?\n/);
        for (const line of lines) {
            if (line.trim()) processed.add(line.trim());
        }
    }
    return processed;
}

async function run() {
    console.log('=== JTMetrics Inner Analysis ===');
    console.log(`Input: ${FILE_INPUT}`);
    console.log(`Output: ${FILE_OUTPUT}`);

    const packages = readPackages();
    console.log(`Loaded ${packages.length} packages from CSV`);

    const processed = getProcessedPackages();
    if (processed.size > 0) {
        console.log(`Resuming: ${processed.size} packages already processed, skipping them`);
    }

    const startTime = Date.now();
    let successCount = 0;
    let errorCount = 0;

    for (let i = 0; i < packages.length; i++) {
        const pkg = packages[i];
        const progress = `[${i + 1}/${packages.length}]`;

        if (processed.has(pkg.name)) {
            continue;
        }

        const pkgDir = path.join(TMP_DIR, pkg.name.replace(/[\/@]/g, '__'));

        try {
            console.log(`${progress} Analyzing ${pkg.name}@${pkg.version}...`);

            const tarballUrl = await getTarballUrl(pkg.name, pkg.version);

            fs.mkdirSync(pkgDir, { recursive: true });
            const fileCount = await downloadAndExtract(tarballUrl, pkgDir);
            console.log(`  Downloaded: ${fileCount} files extracted`);

            const metrics = await runJtmetricsIsolated(pkgDir);

            const result = {
                package: pkg.name,
                version: pkg.version,
                metrics: metrics
            };

            fs.appendFileSync(FILE_OUTPUT, JSON.stringify(result) + '\n', 'utf-8');
            fs.appendFileSync(FILE_TRACKER, pkg.name + '\n', 'utf-8');
            successCount++;
            console.log(`  Done: metrics saved`);

        } catch (err) {
            errorCount++;
            console.error(`  ERROR: ${err.message}`);

            const errorResult = {
                package: pkg.name,
                version: pkg.version,
                error: err.message,
                metrics: null
            };
            fs.appendFileSync(FILE_OUTPUT, JSON.stringify(errorResult) + '\n', 'utf-8');
            fs.appendFileSync(FILE_TRACKER, pkg.name + '\n', 'utf-8');

        } finally {
            rmDir(pkgDir);
        }

        if ((i + 1) % 50 === 0) {
            const elapsed = ((Date.now() - startTime) / 1000 / 60).toFixed(1);
            console.log(`--- Progress: ${successCount} ok, ${errorCount} errors, ${elapsed} min elapsed ---`);
        }
    }

    rmDir(TMP_DIR);

    const totalTime = ((Date.now() - startTime) / 1000 / 60).toFixed(1);
    console.log('\n=== Analysis Complete ===');
    console.log(`Success: ${successCount} | Errors: ${errorCount} | Time: ${totalTime} min`);
    console.log(`Output: ${FILE_OUTPUT}`);
}

run().catch((err) => {
    console.error('FATAL ERROR:', err);
    process.exitCode = 1;
});

