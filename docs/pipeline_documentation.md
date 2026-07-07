# Documentación del Pipeline de Análisis NPM

## 1. Propósito y Metodología
Analizar la fragilidad estructural del ecosistema NPM identificando nodos críticos de infraestructura a través de su topología de red y métricas internas de código.
Se trabaja sobre 5.000 paquetes para evitar sesgos de la periferia. Se extraen tanto métricas de red (Fan-Out, Fan-In) como métricas de código internas.

## 2. Flujo del Pipeline

**Paso 0: Obtención del Top 10k por tamaño**
(`pipeline/0_generate_top10k.py`): Recorre el catálogo paginado de NPM y selecciona los 10.000 paquetes con mayor tamaño. Usa checkpoints para generar `top_10k_by_size.csv`.

**Paso 1: Filtrado por popularidad**
(`pipeline/1_filter_popularity.py`): Consulta la API de descargas semanales y filtra los 10.000 previos para quedarse con los 5.000 más populares en `top_5k_by_downloads.csv`.

**Paso 2: Construcción del grafo de dependencias**
(`pipeline/2_build_graph.py`): Extrae dependencias (prod y dev) para la versión `latest` de los 5.000 paquetes, creando `dependency_graph.json`.

**Paso 3: Cálculo de métricas de red (Fan-Out y Fan-In)**
(`pipeline/3a_calc_fanout.py` y `pipeline/3b_calc_fanin_global.py`): Se calcula el Fan-Out localmente (`fanout_report.csv`) y luego se escanean ~4M de paquetes en el catálogo para calcular el Fan-In global hacia nuestros paquetes (`fanin_global_report.csv`).

**Paso 4: Distancia de versiones**
(`pipeline/4_version_distance.py`): Evalúa la divergencia de versiones entre lo declarado y lo disponible, guardando los resultados en `version_distance.csv`.

**Paso 5: Extracción de metadatos**
(`pipeline/5_package_info.py`): Recolecta metadata adicional (tamaño, número de archivos) y produce `packages_info.csv`.

**Paso 6: Extracción de métricas internas (AST)**
(`pipeline/6_ extract_inner_metrics_jt.js` y `jt_worker.js`): Descarga el código fuente de los paquetes temporalmente y calcula métricas internas en paralelo con `jtmetrics`, emitiendo `inner_metrics_jt.ndjson`.

## 3. Entregables Generados
- `top_10k_by_size.csv`
- `top_5k_by_downloads.csv`
- `dependency_graph.json`
- `fanout_report.csv`
- `fanin_global_report.csv`
- `version_distance.csv`
- `packages_info.csv`
- `inner_metrics_jt.ndjson`

## 4. Ejecución del Pipeline

Ejecución completa usando el orquestador:
```powershell
.\run_pipeline.ps1 -FreshStart
```

Ejecución omitiendo pasos costosos (si ya se hicieron):
```powershell
.\run_pipeline.ps1 -SkipTop10k -SkipFanin
```

Ejecutar solo métricas internas:
```powershell
.\run_pipeline.ps1 -OnlyJTMetrics
```

Ejecutar etapas manualmente:
```powershell
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py
.\.venv\Scripts\python.exe pipeline\1_filter_popularity.py
.\.venv\Scripts\python.exe pipeline\2_build_graph.py
.\.venv\Scripts\python.exe pipeline\3a_calc_fanout.py
.\.venv\Scripts\python.exe pipeline\3b_calc_fanin_global.py
node "pipeline\6_ extract_inner_metrics_jt.js"
```

Prueba de ejecución con paquetes limitados:
```powershell
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py --max-packages 1000
.\.venv\Scripts\python.exe pipeline\3b_calc_fanin_global.py --max-packages 500
```
