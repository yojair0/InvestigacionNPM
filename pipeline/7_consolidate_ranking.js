const fs = require('fs');
const path = require('path');

const DIR_METRICS = path.join(__dirname, '..', 'data', 'metrics');
const FILE_JT = path.join(DIR_METRICS, '04_jtmetrics_resultados.csv');
const FILE_FANIN = path.join(DIR_METRICS, 'fanin_global_report.csv');
const FILE_FANOUT = path.join(DIR_METRICS, 'fanout_report.csv');
const FILE_OUT = path.join(DIR_METRICS, '05_final_ranking_msr.csv');

function parseSimpleCsv(filePath) {
    if (!fs.existsSync(filePath)) return [];
    const content = fs.readFileSync(filePath, 'utf-8').trim();
    if (!content) return [];
    
    const lines = content.split('\n');
    const headers = lines[0].trim().split(',');
    
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        const vals = line.split(',');
        const obj = {};
        for (let j = 0; j < headers.length; j++) {
            obj[headers[j]] = vals[j] || '';
        }
        rows.push(obj);
    }
    return rows;
}

async function run() {
    console.log('--- Iniciando Consolidación de Ranking MSR ---');
    
    console.log(`1. Leyendo ${path.basename(FILE_JT)}...`);
    const jtData = parseSimpleCsv(FILE_JT);
    
    console.log(`2. Leyendo ${path.basename(FILE_FANIN)}...`);
    const faninData = parseSimpleCsv(FILE_FANIN);
    const faninMap = new Map(faninData.map(r => [r.package, r]));
    
    console.log(`3. Leyendo ${path.basename(FILE_FANOUT)}...`);
    const fanoutData = parseSimpleCsv(FILE_FANOUT);
    const fanoutMap = new Map(fanoutData.map(r => [r.package, r]));
    
    // Unificar y calcular score final
    const consolidated = [];
    
    for (const row of jtData) {
        const pkg = row.package;
        const fi = faninMap.get(pkg) || {};
        const fo = fanoutMap.get(pkg) || {};
        
        // Extraer métricas solicitadas
        const jt_instability = parseFloat(row.jt_instability) || 0;
        const jt_in_degree = parseInt(row.jt_in_degree) || 0;
        const jt_out_degree = parseInt(row.jt_out_degree) || 0;
        const jt_dependency_score = parseInt(row.jt_dependency_score) || 0;
        
        const fan_in_total = parseInt(fi.fan_in_total) || 0;
        const fan_out_total = parseInt(fo.fan_out) || parseInt(fo.dependencies_count) || 0;
        
        // --- CORRECCIÓN MATEMÁTICA MSR ---
        // Global Instability = Ce_global / (Ca_global + Ce_global)
        const ca_global = fan_in_total;
        const ce_global = fan_out_total;
        const global_instability = (ca_global + ce_global > 0) ? (ce_global / (ca_global + ce_global)) : 0;
        
        // MSR Risk Score (Kumbartzki et al. / Heurísticas de Fragilidad)
        // Impacto masivo (log de fan_in) multiplicado por su inestabilidad real global
        let risk_score = 0;
        if (fan_in_total > 0) {
            risk_score = (Math.log10(fan_in_total + 1) * 10) * global_instability; 
        }
        
        consolidated.push({
            package: pkg,
            version: row.version || '',
            fan_in_global: fan_in_total,
            fan_out_global: fan_out_total,
            jt_in_degree: jt_in_degree,
            jt_out_degree: jt_out_degree,
            jt_instability: jt_instability.toFixed(4), // Conservado por contexto
            global_instability: global_instability.toFixed(4), // Métrica MSR Real
            jt_dependency_score: jt_dependency_score,
            msr_ecosystem_risk_score: risk_score.toFixed(2)
        });
    }

    // Ordenar por msr_ecosystem_risk_score descendente
    consolidated.sort((a, b) => parseFloat(b.msr_ecosystem_risk_score) - parseFloat(a.msr_ecosystem_risk_score));

    // Escribir CSV
    if (consolidated.length > 0) {
        const headers = Object.keys(consolidated[0]);
        const csvLines = [headers.join(',')];
        
        for (const row of consolidated) {
            const vals = headers.map(h => row[h]);
            csvLines.push(vals.join(','));
        }
        
        fs.writeFileSync(FILE_OUT, csvLines.join('\n'), 'utf-8');
        console.log(`\nÉxito: Se consolidaron ${consolidated.length} paquetes.`);
        console.log(`Salida escrita en: ${FILE_OUT}`);
        
        console.log('\nTop 5 paquetes por Riesgo Ecosistémico (MSR Risk Score):');
        console.table(consolidated.slice(0, 5).map(r => ({
            package: r.package,
            fan_in_global: r.fan_in_global,
            global_instability: r.global_instability,
            risk_score: r.msr_ecosystem_risk_score
        })));
    } else {
        console.log('No se encontraron datos para consolidar.');
    }
}

run().catch(console.error);
