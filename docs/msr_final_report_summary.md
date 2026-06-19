# Resumen de Análisis y Ranking MSR (Métricas de Ecosistema y Grafo)

Fecha: 2026-05-31

Este documento resume los resultados del análisis de la fragmentación, riesgo y acoplamiento en un subconjunto de los paquetes más descargados del registro NPM. Las métricas se han calculado puramente desde información declarativa (metadatos locales del JSON y CSV en espacio local), cruzando el ecosistema global con las dependencias limitadas a los Top 5.000 (de los cuales se analizaron exitosamente 4.974).

## 1. Métricas Consolidadas

En el archivo final `05_final_ranking_msr.csv` se agrupan:
- **`fan_in_global`**: Número de paquetes de *todo* NPM que dependen directa o indirectamente de este paquete.
- **`fan_out_global`**: Número de dependencias únicas (producción y desarrollo) que usa el paquete.
- **`jt_in_degree` / `jt_out_degree`**: Similar al fan-in / fan-out, pero **restringido exclusivamente** a la conexión entre los ~5k analizados.
- **`jt_instability` (Local/Subset)**: Inestabilidad calculada dentro del grafo del top 5k (`Ce / (Ca_subset + Ce)`). Tiende matemáticamente a inflar la inestabilidad.
- **`global_instability`**: Una adaptación matemáticamente estricta de la Inestabilidad de Robert C. Martin (`Ce / (Ca + Ce)`) utilizando los datos **globales**. Esto resuelve la limitación del muestreo: si un paquete depende de 5 paquetes pero es usado por 1.000 globalmente, su `global_instability` será `~0.005` (super estable), mientras que si tiene `global_instability` de `0.90` significa que depende drásticamente de terceros y no es usado casi por nadie en proporción.
- **`jt_dependency_score`**: La suma bruta del acoplamiento.
- **`msr_ecosystem_risk_score`**: Una formulación estricta usando `global_instability × log10(fan_in_global + 1)`. Identifica los "Nodos Críticos y Vulnerables": paquetes con una comunidad razonable usándolos, pero que corren máximo riesgo de "supply-chain failure" por albergar más dependencias que usuarios.

## 2. Hallazgos Clave

### A. La matriz interna de alta dependencia no es densa
Un punto revelador de evaluar las métricas `jt_in_degree` y `jt_out_degree` es que:
- Solo una pequeña fracción de los paquetes ultra-populares dependen "entre sí".
- La gran mayoría (más del 90%) tienen `jt_in_degree = 0` y `jt_out_degree = 0` si lo miramos *estrictamente* dentro del propio grupo de los 5.000 top.
- **Conclusión MSR**: La popularidad se apalanca en el exterior, y la fragilidad real se observa cuando saltamos a todo el grafo (Fan-in / Fan-out Global), confirmando la utilidad limitada de los subsets reducidos si no integramos el universo externo de NPM.

### B. El perfil de Riesgo MSR y la Distorsión del Subset
Al haber re-calculado la **Inestabilidad Global** (`global_instability`) cruzándola con el Fan-In, obtenemos un ranking MSR mucho más sólido y libre del sesgo del tamaño de muestra.
Los verdaderos propulsores de riesgo (MSR Risk Score más altos) demuestran ser superestructuras, SDKs gigantes y agregadores ("megapaquetes"):
- **Integradores y SDKs (ej. `azure` o `coveo-search-ui`)**: Logran scores altísimos porque agrupan docenas/cientos de dependencias subyacentes (`fan_out_global` alto), acercando su inestabilidad a la zona crítica, al mismo tiempo que su Fan-In Global sigue siendo lo suficientemente importante como para propagar un fallo.
- **Micro-Librerías Puras (los verdaderos pilares de NPM)**: Históricamente se culpa a paquetes masivos (p.ej. `next`, `react`), pero bajo el rigor de la `global_instability`, sus millones de descargas y enorme Fan-In neutralizan matemáticamente sus dependencias, categorizándolos correctamente como "Altamente Estables" ($I \approx 0$).

### C. Patrones de acoplamiento MSR
Los paquetes con `global_instability` alta (`> 0.8`) no son "malos", sino que obedecen a un patrón de diseño que denominamos **Fachada Estructural**:
- Incorporan un daño potencial extremo ("supply chain risk") por las docenas de deps de donde extraen código (Ce). 
- El hecho de analizarlos con `global_instability` en el script consolidador (`7_consolidate_ranking.js`) depuró el "ruido de muestreo" en la investigación, confirmando que usar métricas locales para un ecosistema abierto arroja falsos positivos de vulnerabilidad.

## 3. Limitaciones Finales
De acuerdo con las restricciones metodológicas asumidas:
- Ninguna de estas métricas computó AST interno ni resolvió *imports/requires* directos en código (como en la definición purista original de `JTMetrics`), sino que se extrajo el **perfil de arquitectura estructural** por medio de los manifiestos (`package.json`).
- Hemos operado bajo la hipótesis segura de que analizar todo el ecosistema y no solo el subset para dependencias entrantes (Fan In) es imprescindible, pero la *Instability* adaptada sigue arrojando un panorama interno útil para aislar a los "nodos propagadores".