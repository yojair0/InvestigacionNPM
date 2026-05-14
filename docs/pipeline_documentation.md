# Documentación técnica del pipeline MSR UCN (NPM)

## 1. Propósito

Implementar una replicación operacional del protocolo de estudio aplicada al ecosistema NPM, orientada a analizar la fragilidad estructural del registro y a identificar nodos de infraestructura críticos.

Objetivo central:
- Identificar nodos de infraestructura y cuantificar fragilidad estructural mediante topología de dependencias y métricas derivadas (Fan‑In, Fan‑Out, risk score).

Resumen del enunciado metodológico:
- Operar sobre un ecosistema de límite cerrado compuesto por 5.000 paquetes filtrados para aislar el núcleo de red y evitar distorsiones por la periferia del registro.

## 2. Principios metodológicos clave

1) Aislamiento del núcleo
- Aislar un subconjunto controlado (5.000 paquetes) para medir carga de infraestructura interna y evitar sesgos generados por paquetes de usuario final o código muerto en la periferia.

2) Masa estructural y relevancia de uso
- Priorizar paquetes con tamaño estructural significativo (top 10k por bytes) y con adopción medible (top 5k por descargas) para centrar el análisis en módulos de impacto real.

3) Identificación de riesgo en cascada
- Construir la topología de dependencias entre la élite del software para identificar Nodos de Infraestructura capaces de producir efectos en cascada y puntos únicos de fallo.

4) Reproducibilidad y trazabilidad
- Implementar checkpointing, reintentos robustos y control de versiones de datos para permitir ejecutar, pausar y reanudar el estudio con trazas reproducibles.

## 3. Flujo del pipeline (resumen operativo)

1. Generar `top_10k_pesados.csv`: recorrer el catálogo NPM y seleccionar 10.000 paquetes con mayor tamaño (dist.unpackedSize o dist.size).
2. Generar `top_5000_popular.csv`: filtrar los 10.000 por descargas semanales y seleccionar los 5.000 más usados.
3. Construir `grafo_final_ucn.json`: extraer `dependencies` y `devDependencies` para la versión `dist-tags.latest` de cada paquete.
4. Generar `reporte_metricas_ucn.csv`: calcular `fan_out`, `fan_in` (intra‑subconjunto) y `risk_score` para cada nodo.
5. Generar `shortlist_top50.csv`: priorizar top 50 por `fan_in` interno para auditoría inicial.

Artefactos esperados:
- `top_10k_pesados.csv`
- `top_5000_popular.csv`
- `grafo_final_ucn.json`
- `reporte_metricas_ucn.csv`
- `shortlist_top50.csv`
- `checkpoint_top_10k_pesados.json` (control de continuidad)

## 4. Documentación por script (resumen técnico)

4.1 `0_generador_top_10k_pesados.py`
- Objetivo: recorrer el catálogo NPM y conservar los 10.000 paquetes de mayor tamaño.
- Entradas: `https://replicate.npmjs.com/_all_docs`, `https://registry.npmjs.org/{paquete}/latest`.
- Salida: `top_10k_pesados.csv` (package_name, size_bytes, size_source).
- Mecanismo: paginar catálogo, extraer tamaños, mantener heap mínimo de k=10000, checkpoint incremental.
- Resiliencia: reintentos exponenciales con jitter, parsing defensivo, manejo de `Retry-After`.

4.2 `1_filtro_popularidad.py`
- Objetivo: seleccionar los 5.000 paquetes con mayor descarga semanal dentro del subconjunto pesado.
- Entradas: `top_10k_pesados.csv`, API `https://api.npmjs.org/downloads/point/last-week/{paquete}`.
- Salida: `top_5000_popular.csv` (package_name, downloads).
- Mecanismo: peticiones concurrentes con ThreadPoolExecutor (max_workers configurable), reintentos, ordenamiento por descargas.

4.3 `2_procesador_grafo.py`
- Objetivo: construir la topología de dependencias internas para los 5.000 paquetes.
- Entradas: `top_5000_popular.csv`, `https://registry.npmjs.org/{paquete}`.
- Salida: `grafo_final_ucn.json` (clave por paquete con `dependencies` y `devDependencies`).
- Mecanismo: resolver `dist-tags.latest`, extraer campos, normalizar estructuras, mantener aristas hacia paquetes internos y externas (registrar distinción).

4.4 `3_metricas_infra_nodes.py`
- Objetivo: calcular métricas estructurales y generar reporte ordenado.
- Entradas: `grafo_final_ucn.json`.
- Salida: `reporte_metricas_ucn.csv` (paquete, fan_out, fan_in, risk_score).
- Mecanismo: calcular `fan_out = |dependencies| + |devDependencies|`, calcular `fan_in` contando referencias desde otros nodos dentro del subconjunto, computar `risk_score = fan_in + fan_out` y ordenar por `fan_in`.

4.5 `4_generar_shortlist_top50.py`
- Objetivo: generar `shortlist_top50.csv` con top 50 por `fan_in` interno para auditoría priorizada.
- Salida: `shortlist_top50.csv` (rank, package, fan_in, fan_out, risk_score).

4.6 Orquestación (`run_pipeline_ucn.ps1`)
- Objetivo: ejecutar las etapas de forma controlada en entorno Windows con `.venv`.
- Mecanismo: admitir modos `OnlyTop10k`, `OnlyFilter`, `OnlyGraph`, `SkipTop10k`, `FreshStart`, y gestionar dependencias (`requests`) en el entorno virtual.

## 5. Validaciones operativas (checks a ejecutar tras cada etapa)

- Verificar `top_10k_pesados.csv`: conteo = 10000, unicidad = 10000, orden descendente por `size_bytes`.
- Verificar `top_5000_popular.csv`: conteo = 5000, unicidad = 5000, pertenencia al `top_10k_pesados.csv`.
- Verificar `grafo_final_ucn.json`: existencia del fichero y 5000 nodos en la raíz.
- Verificar `reporte_metricas_ucn.csv`: existencia, 5000 filas, orden por `fan_in` descendente.

## 6. Interpretación de métricas y finalidad aplicada

- Fan‑In: identificar nodos con alto número de consumidores internos (indicador de concentración y posible punto único de fallo).
- Fan‑Out: identificar nodos con alta exposición saliente (mayor superficie hacia dependencias externas o internas).
- Risk Score: combinar Fan‑In y Fan‑Out para priorizar análisis operativos iniciales.

Finalidad aplicada del análisis:
- Aislar el núcleo de la red para medir carga de infraestructura y revelar los Nodos de Infraestructura verdaderamente críticos dentro de la élite del software.
- Evaluar dependencias cruzadas entre paquetes de alto uso para detectar rutas de propagación de fallo en cascada.
- Proporcionar una shortlist priorizada para auditoría técnica, escaneo de vulnerabilidades y verificación de mantenibilidad.

## 7. Limitaciones y notas metodológicas

1. Snapshot temporal: representar el estado del registro en el momento de la ejecución.
2. Fan‑In interno: `fan_in` en `reporte_metricas_ucn.csv` corresponde a entradas provenientes exclusivamente desde el subconjunto de 5.000 paquetes; para contabilizar dependents desde todo NPM ejecutar etapa adicional de conteo global o usar datasets agregados.
3. Versión de referencia: analizar `dist-tags.latest` por paquete (no historial completo de versiones).
4. Heurística de riesgo: `risk_score = fan_in + fan_out` constituye una métrica inicial; complementar con centralidad avanzada y datos de mantenimiento para decisiones operativas.

## 8. Opciones para extensión: fan_in global

- Ejecutar job checkpointed sobre `replicate.npmjs.com/_all_docs` y contar referencias hacia los 5k para obtener `fan_in_global` (exactitud alta, coste computacional y de red elevado).
- Consultar BigQuery public npm dataset para extraer counts de dependents (rapidez, requiere credenciales/consumo).
- Realizar muestreo (p. ej. top 100k) para estimar `fan_in_global` con menor coste.

## 9. Reproducibilidad (comandos ejemplares)

Ejecutar pipeline completo (Windows PowerShell, entorno con `.venv` activado):

```powershell
.\run_pipeline_ucn.ps1 -FreshStart
```

Ejecutar solo métricas (si el grafo ya existe):

```powershell
.\.venv\Scripts\python.exe .\3_metricas_infra_nodes.py
```

## 10. Entregables finales

- `top_10k_pesados.csv`
- `top_5000_popular.csv`
- `grafo_final_ucn.json`
- `reporte_metricas_ucn.csv`
- `shortlist_top50.csv`
- `checkpoint_top_10k_pesados.json`

## 11. Próximos pasos recomendados

- Generar `shortlist_top50.csv` y revisar top 50 por `fan_in` interno para auditoría inmediata.
- Decidir sobre ejecución de etapa de `fan_in_global` o uso de dataset externo según recursos y plazos.

