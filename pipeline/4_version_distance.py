#!/usr/bin/env python3
"""Calcula la distancia de versiones entre la declarada y la ultima disponible.

Para cada dependencia de cada paquete, consulta la version latest en el registry
y compara contra la version declarada en el package.json.

La version latest de cada dependencia se cachea en memoria para no consultar
la misma dependencia mas de una vez aunque aparezca en multiples paquetes.

Entrada:  data/raw/dependency_graph.json
Salida:   data/metrics/version_distance.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

try:
    import requests
    from requests.exceptions import RequestException
except ImportError as exc:
    raise SystemExit("Dependencia faltante: instala con: pip install requests") from exc

REGISTRY_TEMPLATE = "https://registry.npmjs.org/{}/latest"

DEFAULT_INPUT_JSON = Path("data/raw/dependency_graph.json")
DEFAULT_OUTPUT_CSV = Path("data/metrics/version_distance.csv")

DEFAULT_WORKERS = 20
DEFAULT_MAX_RETRIES = 5
DEFAULT_REQUEST_TIMEOUT = 20

_thread_local = threading.local()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calcula distancia de versiones entre declarada y latest en npm."
    )
    parser.add_argument("--input-json", type=Path, default=DEFAULT_INPUT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser.parse_args()


def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({"Accept": "application/json",
                           "User-Agent": "npm-version-distance/1.0"})
        _thread_local.session = s
    return _thread_local.session


def compute_backoff(attempt: int) -> float:
    return min((2 ** (attempt - 1)) + random.uniform(0.0, 0.5), 60.0)


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """Extrae (major, minor, patch) de un string de version semver.

    Maneja prefijos como ^, ~, >=, >, etc. y sufijos como -beta.1.
    Retorna (0, 0, 0) si no se puede parsear.
    """
    if not version_str or version_str in ("*", "latest", "x", ""):
        return (0, 0, 0)

    # Tomar solo la primera parte si hay rangos como "1.0.0 || 2.0.0" o "1.0.0 - 2.0.0"
    version_str = version_str.split("||")[0].strip()
    version_str = version_str.split(" - ")[0].strip()

    # Quitar operadores al inicio
    for op in (">=", "<=", "!=", "^", "~", ">", "<", "=", "v"):
        if version_str.startswith(op):
            version_str = version_str[len(op):].strip()

    # Quitar sufijos de pre-release (-alpha, -beta, etc.)
    version_str = version_str.split("-")[0].strip()
    version_str = version_str.split("+")[0].strip()

    parts = version_str.split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 and parts[0] not in ("x", "*", "") else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1] not in ("x", "*", "") else 0
        patch = int(parts[2]) if len(parts) > 2 and parts[2] not in ("x", "*", "") else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def fetch_latest_version(dep_name: str) -> Tuple[str, Optional[str]]:
    """Consulta registry.npmjs.org para obtener la version latest de una dependencia.

    Retorna (dep_name, latest_version_str | None).
    """
    session = get_session()
    url = REGISTRY_TEMPLATE.format(quote(dep_name, safe=""))

    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            status = response.status_code

            if status == 200:
                try:
                    payload = response.json()
                    version = payload.get("version")
                    return dep_name, (version if isinstance(version, str) else None)
                except ValueError:
                    return dep_name, None

            if status == 404:
                return dep_name, None

            if status == 429 or 500 <= status < 600:
                time.sleep(compute_backoff(attempt))
                continue

            return dep_name, None

        except Exception:
            if attempt >= DEFAULT_MAX_RETRIES:
                return dep_name, None
            time.sleep(compute_backoff(attempt))

    return dep_name, None


def load_graph(json_path: Path) -> Dict:
    if not json_path.exists():
        raise FileNotFoundError(
            f"No se encontro: {json_path}. Generalo con 2_build_graph.py"
        )
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def collect_unique_deps(graph: Dict) -> Dict[str, List[Tuple[str, str, str]]]:
    """Recorre el grafo y agrupa los pares (package, declared_version) por dependencia.

    Retorna: {dep_name: [(package_name, declared_version, dep_type), ...]}
    donde dep_type es 'prod' o 'dev'.
    """
    dep_map: Dict[str, List[Tuple[str, str, str]]] = {}

    for package_name, package_data in graph.items():
        for dep_name, declared_version in (package_data.get("dependencies") or {}).items():
            dep_map.setdefault(dep_name, []).append(
                (package_name, str(declared_version), "prod"))

        for dep_name, declared_version in (package_data.get("devDependencies") or {}).items():
            dep_map.setdefault(dep_name, []).append(
                (package_name, str(declared_version), "dev"))

    return dep_map


def build_rows(
    dep_map: Dict[str, List[Tuple[str, str, str]]],
    latest_cache: Dict[str, Optional[str]],
) -> List[Dict]:
    """Construye las filas del CSV cruzando versiones declaradas con las latest."""
    rows = []

    for dep_name, usages in dep_map.items():
        latest_str = latest_cache.get(dep_name)
        latest = parse_semver(latest_str) if latest_str else (0, 0, 0)

        for package_name, declared_version, dep_type in usages:
            declared = parse_semver(declared_version)

            major_diff = max(0, latest[0] - declared[0])
            minor_diff = max(0, latest[1] - declared[1]) if latest[0] == declared[0] else 0
            patch_diff = max(0, latest[2] - declared[2]) if (
                latest[0] == declared[0] and latest[1] == declared[1]) else 0

            rows.append({
                "package": package_name,
                "dependency": dep_name,
                "dep_type": dep_type,
                "version_declared": declared_version,
                "latest_version": latest_str or "unknown",
                "major_diff": major_diff,
                "minor_diff": minor_diff,
                "patch_diff": patch_diff,
            })

    return rows


def save_csv(rows: List[Dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["package", "dependency", "dep_type", "version_declared",
                  "latest_version", "major_diff", "minor_diff", "patch_diff"]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV generado: {output_path} | filas: {len(rows)}")


def main() -> None:
    args = parse_args()
    started_at = time.time()

    graph = load_graph(args.input_json)
    print(f"Grafo cargado: {len(graph)} paquetes")

    dep_map = collect_unique_deps(graph)
    unique_deps = list(dep_map.keys())
    print(f"Dependencias unicas a consultar: {len(unique_deps)}")

    # Obtener latest version para cada dependencia unica
    latest_cache: Dict[str, Optional[str]] = {}
    completed = 0
    total = len(unique_deps)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_latest_version, dep): dep for dep in unique_deps}
        for future in as_completed(futures):
            dep_name, latest = future.result()
            latest_cache[dep_name] = latest
            completed += 1
            if completed % 1000 == 0 or completed == total:
                print(f"Progreso: {completed}/{total} dependencias consultadas")

    print(f"Cache de versiones completada. Calculando distancias...")

    rows = build_rows(dep_map, latest_cache)
    save_csv(rows, args.output_csv)

    elapsed = time.time() - started_at
    print(f"Proceso finalizado en {elapsed:.1f}s | filas generadas: {len(rows)}")


if __name__ == "__main__":
    main()
