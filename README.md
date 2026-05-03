# Pipeline MSR UCN sobre NPM

## Propósito

Documentar y reproducir un pipeline para analizar la fragilidad estructural del ecosistema NPM mediante selección de paquetes, construcción de grafo de dependencias y cálculo de métricas de infraestructura.

## Alcance metodológico

- Operar sobre un subconjunto cerrado de 5.000 paquetes.
- Aislar el núcleo estructural del registro para evitar distorsiones por la periferia.
- Medir `fan_in`, `fan_out` y `risk_score` sobre el grafo interno del subconjunto.
- Priorizar nodos críticos para auditoría técnica y análisis de riesgo en cascada.

## Estructura principal

- `0_generador_top_10k_pesados.py`: seleccionar los 10.000 paquetes de mayor tamaño.
- `1_filtro_popularidad.py`: filtrar los 5.000 paquetes con mayor descarga semanal dentro del subconjunto pesado.
- `2_procesador_grafo.py`: construir el grafo de `dependencies` y `devDependencies`.
- `3_metricas_infra_nodes.py`: calcular `fan_in`, `fan_out` y `risk_score`.
- `4_generar_shortlist_top50.py`: generar una lista priorizada de los 50 nodos con mayor `fan_in` interno.
- `run_pipeline_ucn.ps1`: orquestar la ejecución en Windows.

## Requisitos

- Python 3.11 o compatible.
- Entorno virtual en `.venv`.
- Dependencia externa: `requests`.

Instalación:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecución

Ejecución completa:

```powershell
.\run_pipeline_ucn.ps1 -FreshStart
```

Ejecución de métricas sobre grafo existente:

```powershell
.\.venv\Scripts\python.exe .\3_metricas_infra_nodes.py
```

Generación de shortlist priorizada:

```powershell
.\.venv\Scripts\python.exe .\4_generar_shortlist_top50.py
```

## Salidas principales

- `top_10k_pesados.csv`
- `top_5000_popular.csv`
- `grafo_final_ucn.json`
- `reporte_metricas_ucn.csv`
- `shortlist_top50.csv`

## Nota metodológica

- Calcular `fan_in` interno dentro del subconjunto de 5.000 para aislar la carga estructural del núcleo.
- Reservar `fan_in_global` para una etapa adicional si se requiere cobertura del ecosistema completo.
