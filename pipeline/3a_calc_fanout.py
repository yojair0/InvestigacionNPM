#!/usr/bin/env python3
"""Calculates the fan-out metrics from the dependency graph."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, List

DEFAULT_INPUT_JSON = Path("data/raw/dependency_graph.json")
DEFAULT_OUTPUT_CSV = Path("data/metrics/fanout_report.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calcula fan-out de los 5k paquetes NPM desde el grafo de dependencias."
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_INPUT_JSON,
        help=f"Ruta del grafo de dependencias JSON (default: {DEFAULT_INPUT_JSON}).",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help=f"Ruta del CSV de salida (default: {DEFAULT_OUTPUT_CSV}).",
    )
    return parser.parse_args()


def load_graph(json_path: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    if not json_path.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo de entrada: {json_path}. "
            "Generalo primero con 2_build_graph.py"
        )

    with json_path.open("r", encoding="utf-8") as f:
        graph = json.load(f)

    if not isinstance(graph, dict):
        raise ValueError("El JSON de entrada debe ser un objeto en la raiz.")

    print(f"[INFO] Graph loaded: {len(graph)} packages")
    return graph


def calc_fanout(graph: Dict[str, Dict[str, Dict[str, str]]]) -> List[Dict]:
    rows: List[Dict] = []

    for package_name, package_data in graph.items():
        deps = package_data.get("dependencies")
        dev_deps = package_data.get("devDependencies")

        if not isinstance(deps, dict):
            deps = {}
        if not isinstance(dev_deps, dict):
            dev_deps = {}

        dep_count = len(deps)
        dev_dep_count = len(dev_deps)
        fan_out = dep_count + dev_dep_count

        rows.append({
            "package": package_name,
            "fan_out": fan_out,
            "dependencies_count": dep_count,
            "dev_dependencies_count": dev_dep_count,
        })

    return rows


def save_csv(rows: List[Dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["package", "fan_out", "dependencies_count", "dev_dependencies_count"]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[INFO] CSV generated: {output_path} | rows: {len(rows)}")


def main() -> None:
    print("---- [STEP 3A] CALCULATE FAN OUT ----")
    args = parse_args()
    started_at = time.time()

    try:
        graph = load_graph(args.input_json)
        rows = calc_fanout(graph)
        save_csv(rows, args.output_csv)

        elapsed = time.time() - started_at
        print(f"[DONE] Process finished in {elapsed:.1f}s | rows: {len(rows)}")

    except FileNotFoundError as exc:
        print(f"[error] {exc}")
    except ValueError as exc:
        print(f"[error] {exc}")
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON: {exc}")
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
    except Exception as exc:
        print(f"[ERROR] Unhandled failure: {exc}")


if __name__ == "__main__":
    main()
