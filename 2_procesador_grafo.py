#!/usr/bin/env python3
"""Construye el grafo de dependencias/devDependencies para paquetes NPM."""

from __future__ import annotations

import csv
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

try:
    import requests
    from requests.exceptions import RequestException
except ImportError as exc:
    raise SystemExit(
        "Dependencia faltante: requests. Instala con: pip install requests"
    ) from exc

INPUT_CSV = Path("top_5000_popular.csv")
OUTPUT_JSON = Path("grafo_final_ucn.json")
REGISTRY_TEMPLATE = "https://registry.npmjs.org/{}"
MAX_WORKERS = 10
MAX_RETRIES = 6
REQUEST_TIMEOUT = 25

_thread_local = threading.local()


def get_session() -> requests.Session:
    """Crea o reutiliza una sesion HTTP por hilo para reducir overhead."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "ucn-msr-npm-graph-processor/1.0",
            }
        )
        _thread_local.session = session
    return _thread_local.session


def parse_retry_after(retry_after_value: Optional[str]) -> Optional[float]:
    """Convierte Retry-After a segundos cuando existe y es valido."""
    if not retry_after_value:
        return None
    try:
        return max(0.0, float(retry_after_value))
    except ValueError:
        return None


def compute_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    """Calcula espera con backoff exponencial y jitter para retries."""
    if retry_after is not None:
        return min(max(retry_after, 1.0), 120.0)
    jitter = random.uniform(0.0, 0.5)
    return min((2 ** (attempt - 1)) + jitter, 120.0)


def empty_dependency_block() -> Dict[str, Dict[str, str]]:
    """Retorna estructura vacia para un paquete sin dependencias o con error."""
    return {"dependencies": {}, "devDependencies": {}}


def read_package_names(csv_path: Path) -> List[str]:
    """Lee paquetes desde CSV usando la columna package_name y elimina duplicados."""
    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontro el archivo de entrada: {csv_path}")

    package_names: List[str] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "package_name" not in reader.fieldnames:
            raise ValueError(
                "El CSV de entrada debe contener una columna 'package_name'."
            )

        for row in reader:
            package_name = (row.get("package_name") or "").strip()
            if package_name:
                package_names.append(package_name)

    unique_package_names = list(dict.fromkeys(package_names))
    print(
        f"Paquetes leidos: {len(package_names)} | Paquetes unicos: {len(unique_package_names)}"
    )
    return unique_package_names


def extract_dependencies_from_payload(
    payload: Dict[str, object], package_name: str
) -> Tuple[Dict[str, Dict[str, str]], Optional[str]]:
    """Extrae dependencies y devDependencies de la version marcada como latest."""
    dist_tags = payload.get("dist-tags")
    if not isinstance(dist_tags, dict):
        dist_tags = {}

    latest_version = dist_tags.get("latest")
    if not isinstance(latest_version, str):
        return empty_dependency_block(), "No existe dist-tags.latest"

    versions = payload.get("versions")
    if not isinstance(versions, dict):
        return empty_dependency_block(), "No existe versions en metadata"

    latest_metadata = versions.get(latest_version)
    if not isinstance(latest_metadata, dict):
        return empty_dependency_block(), (
            f"No existe metadata para latest={latest_version}"
        )

    dependencies = latest_metadata.get("dependencies")
    dev_dependencies = latest_metadata.get("devDependencies")

    if not isinstance(dependencies, dict):
        dependencies = {}

    if not isinstance(dev_dependencies, dict):
        dev_dependencies = {}

    result = {
        "dependencies": dependencies,
        "devDependencies": dev_dependencies,
    }

    if not dependencies and not dev_dependencies:
        return result, f"{package_name} sin dependencies ni devDependencies"

    return result, None


def fetch_package_graph(
    package_name: str,
) -> Tuple[str, Dict[str, Dict[str, str]], Optional[str]]:
    """Consulta el registro NPM y obtiene dependencias de la version latest."""
    encoded_package_name = quote(package_name, safe="")
    url = REGISTRY_TEMPLATE.format(encoded_package_name)
    session = get_session()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            status_code = response.status_code

            if status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return package_name, empty_dependency_block(), "JSON invalido"

                dependencies_block, note = extract_dependencies_from_payload(
                    payload, package_name
                )
                return package_name, dependencies_block, note

            if status_code == 404:
                return package_name, empty_dependency_block(), "Paquete no encontrado (404)"

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = compute_backoff(attempt, retry_after)
                print(
                    f"[retry] {package_name} | HTTP {status_code} | intento {attempt}/{MAX_RETRIES} | espera {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            return (
                package_name,
                empty_dependency_block(),
                f"HTTP inesperado {status_code}",
            )

        except RequestException as exc:
            if attempt >= MAX_RETRIES:
                return (
                    package_name,
                    empty_dependency_block(),
                    f"Error de red tras {MAX_RETRIES} intentos: {exc}",
                )
            wait_seconds = compute_backoff(attempt)
            print(
                f"[retry] {package_name} | error de red: {exc} | intento {attempt}/{MAX_RETRIES} | espera {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)

        except Exception as exc:
            return package_name, empty_dependency_block(), f"Error inesperado: {exc}"

    return package_name, empty_dependency_block(), "Se agotaron los reintentos"


def build_graph(
    package_names: Iterable[str],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Procesa paquetes en paralelo y consolida el grafo final en memoria."""
    package_list = list(package_names)
    total_packages = len(package_list)

    graph: Dict[str, Dict[str, Dict[str, str]]] = {}
    incidents = 0

    print(
        f"Iniciando construccion de grafo para {total_packages} paquetes con {MAX_WORKERS} workers..."
    )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_package = {
            executor.submit(fetch_package_graph, package_name): package_name
            for package_name in package_list
        }

        completed = 0
        for future in as_completed(future_to_package):
            package_from_future = future_to_package[future]

            try:
                package_name, dependencies_block, note = future.result()
            except Exception as exc:
                package_name = package_from_future
                dependencies_block = empty_dependency_block()
                note = f"Error al resolver future: {exc}"

            graph[package_name] = dependencies_block

            if note:
                incidents += 1
                print(f"[warn] {package_name}: {note}")

            completed += 1
            if completed % 100 == 0 or completed == total_packages:
                print(
                    f"Progreso: {completed}/{total_packages} ({completed / total_packages:.1%}) | incidencias: {incidents}"
                )

    return graph


def save_graph(graph: Dict[str, Dict[str, Dict[str, str]]], output_path: Path) -> None:
    """Guarda el grafo consolidado como JSON con indentacion de 4 espacios."""
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(graph, json_file, indent=4)

    print(f"Archivo generado: {output_path} | nodos: {len(graph)}")


def main() -> None:
    """Orquesta lectura del CSV, extraccion de dependencias y escritura del JSON final."""
    started_at = time.time()

    try:
        package_names = read_package_names(INPUT_CSV)
        if not package_names:
            print("No hay paquetes para procesar. Se aborta ejecucion.")
            return

        graph = build_graph(package_names)
        save_graph(graph, OUTPUT_JSON)

        elapsed = time.time() - started_at
        print(f"Proceso finalizado en {elapsed:.1f} segundos.")

    except FileNotFoundError as exc:
        print(f"[error] {exc}")
    except ValueError as exc:
        print(f"[error] {exc}")
    except KeyboardInterrupt:
        print("\nEjecucion interrumpida por usuario.")
    except Exception as exc:
        print(f"[error] Falla no controlada: {exc}")


if __name__ == "__main__":
    main()
