#!/usr/bin/env python3
"""Calcula Fan-In y Fan-Out sobre un grafo de dependencias NPM.

Entrada esperada:
- grafo_final_ucn.json

Salida:
- reporte_metricas_ucn.csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

INPUT_JSON = Path("grafo_final_ucn.json")
OUTPUT_CSV = Path("reporte_metricas_ucn.csv")


def as_dict(value: Any) -> Dict[str, Any]:
    """Retorna value si es diccionario; en otro caso retorna dict vacio."""
    if isinstance(value, dict):
        return value
    return {}


def load_graph(json_path: Path) -> Dict[str, Dict[str, Any]]:
    """Carga el JSON del grafo y valida que tenga estructura de diccionario."""
    if not json_path.exists():
        raise FileNotFoundError(f"No se encontro el archivo de entrada: {json_path}")

    with json_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError("El JSON de entrada debe ser un objeto (dict) en la raiz.")

    clean_graph: Dict[str, Dict[str, Any]] = {}
    for package_name, package_data in payload.items():
        if not isinstance(package_name, str) or not package_name.strip():
            continue

        clean_graph[package_name] = as_dict(package_data)

    if not clean_graph:
        raise ValueError("El JSON cargado no contiene paquetes validos.")

    return clean_graph


def initialize_metrics(graph: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, int | str]]:
    """Inicializa las metricas por paquete y calcula Fan-Out."""
    metrics: Dict[str, Dict[str, int | str]] = {}

    for package_name, package_data in graph.items():
        dependencies = as_dict(package_data.get("dependencies"))
        dev_dependencies = as_dict(package_data.get("devDependencies"))

        fan_out = len(dependencies) + len(dev_dependencies)

        metrics[package_name] = {
            "paquete": package_name,
            "fan_out": fan_out,
            "fan_in": 0,
            "risk_score": 0,
        }

    return metrics


def iter_unique_targets(package_data: Mapping[str, Any]) -> Iterable[str]:
    """Itera dependencias unicas (dependencies + devDependencies) de un paquete."""
    dependencies = as_dict(package_data.get("dependencies"))
    dev_dependencies = as_dict(package_data.get("devDependencies"))

    targets = set(dependencies.keys()) | set(dev_dependencies.keys())
    for target in targets:
        if isinstance(target, str) and target.strip():
            yield target


def compute_fan_in(
    graph: Mapping[str, Mapping[str, Any]],
    metrics: Dict[str, Dict[str, int | str]],
) -> None:
    """Calcula Fan-In para cada paquete dentro del conjunto de nodos del grafo."""
    package_names = set(metrics.keys())

    processed = 0
    total = len(graph)

    for _, package_data in graph.items():
        for target in iter_unique_targets(package_data):
            if target in package_names:
                metrics[target]["fan_in"] = int(metrics[target]["fan_in"]) + 1

        processed += 1
        if processed % 500 == 0 or processed == total:
            print(f"Progreso Fan-In: {processed}/{total} paquetes")


def compute_risk_score(metrics: Dict[str, Dict[str, int | str]]) -> None:
    """Calcula Score de Riesgo simple: Fan-In + Fan-Out."""
    for row in metrics.values():
        fan_in = int(row["fan_in"])
        fan_out = int(row["fan_out"])
        row["risk_score"] = fan_in + fan_out


def export_metrics_csv(metrics: Mapping[str, Dict[str, int | str]], output_path: Path) -> None:
    """Exporta metricas a CSV ordenadas descendentemente por fan_in."""
    ordered_rows = sorted(
        metrics.values(),
        key=lambda row: (
            int(row["fan_in"]),
            int(row["risk_score"]),
            int(row["fan_out"]),
            str(row["paquete"]),
        ),
        reverse=True,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["paquete", "fan_out", "fan_in", "risk_score"],
        )
        writer.writeheader()
        writer.writerows(ordered_rows)


def main() -> None:
    """Orquesta carga del grafo, calculo de metricas y exportacion de reporte."""
    print(f"Leyendo grafo desde: {INPUT_JSON}")
    graph = load_graph(INPUT_JSON)
    print(f"Paquetes detectados en grafo: {len(graph)}")

    print("Inicializando metricas y calculando Fan-Out...")
    metrics = initialize_metrics(graph)

    print("Calculando Fan-In (impacto cruzado)...")
    compute_fan_in(graph, metrics)

    print("Calculando Score de Riesgo...")
    compute_risk_score(metrics)

    print(f"Exportando reporte a: {OUTPUT_CSV}")
    export_metrics_csv(metrics, OUTPUT_CSV)

    print("Proceso completado.")
    print(f"Filas exportadas: {len(metrics)}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(f"[error] {exc}")
    except ValueError as exc:
        print(f"[error] {exc}")
    except json.JSONDecodeError as exc:
        print(f"[error] JSON invalido: {exc}")
    except KeyboardInterrupt:
        print("\nEjecucion interrumpida por usuario.")
    except Exception as exc:
        print(f"[error] Falla no controlada: {exc}")
