// Worker process: receives a package directory path, runs jtmetrics, returns result
const path = require('path');

async function analyzePackage(codePath) {
    const { calculateMetrics } = await import('jtmetrics');
    const metrics = await calculateMetrics({
        codePath: codePath,
        useDefaultMetrics: true
    });
    return metrics;
}

const codePath = process.argv[2];
if (!codePath) {
    process.send({ error: 'No codePath provided' });
    process.exit(1);
}

analyzePackage(codePath)
    .then((metrics) => {
        process.send({ success: true, metrics });
    })
    .catch((err) => {
        process.send({ success: false, error: err.message });
    });
