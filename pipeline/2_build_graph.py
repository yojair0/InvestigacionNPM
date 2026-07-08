#!/usr/bin/env python3
"""Builds a dependency and devDependency graph for the NPM packages."""

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

INPUT_CSV = Path("data/raw/top_5k_by_downloads.csv")
OUTPUT_JSON = Path("data/raw/dependency_graph.json")
REGISTRY_TEMPLATE = "https://registry.npmjs.org/{}"
MAX_WORKERS = 10
MAX_RETRIES = 6
REQUEST_TIMEOUT = 25

_thread_local = threading.local()


def get_session() -> requests.Session:
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
    if not retry_after_value:
        return None
    try:
        return max(0.0, float(retry_after_value))
    except ValueError:
        return None


def compute_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    if retry_after is not None:
        return min(max(retry_after, 1.0), 120.0)
    jitter = random.uniform(0.0, 0.5)
    return min((2 ** (attempt - 1)) + jitter, 120.0)


def empty_dependency_block() -> Dict[str, Dict[str, str]]:
    return {"dependencies": {}, "devDependencies": {}}


def read_package_names(csv_path: Path) -> List[str]:
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
        f"Packages read: {len(package_names)} | Unique packages: {len(unique_package_names)}"
    )
    return unique_package_names


def extract_dependencies_from_payload(
    payload: Dict[str, object], package_name: str
) -> Tuple[Dict[str, Dict[str, str]], Optional[str]]:
    dist_tags = payload.get("dist-tags")
    if not isinstance(dist_tags, dict):
        dist_tags = {}

    latest_version = dist_tags.get("latest")
    if not isinstance(latest_version, str):
        return empty_dependency_block(), "Missing dist-tags.latest"

    versions = payload.get("versions")
    if not isinstance(versions, dict):
        return empty_dependency_block(), "Missing versions in metadata"

    latest_metadata = versions.get(latest_version)
    if not isinstance(latest_metadata, dict):
        return empty_dependency_block(), (
            f"Missing metadata for latest={latest_version}"
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
        return result, f"{package_name} has no dependencies or devDependencies"

    return result, None


def fetch_package_graph(
    package_name: str,
) -> Tuple[str, Dict[str, Dict[str, str]], Optional[str]]:
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
                    return package_name, empty_dependency_block(), "Invalid JSON"

                dependencies_block, note = extract_dependencies_from_payload(
                    payload, package_name
                )
                return package_name, dependencies_block, note

            if status_code == 404:
                return package_name, empty_dependency_block(), "Package not found (404)"

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = compute_backoff(attempt, retry_after)
                print(
                    f"[RETRY] [npm_api] | {package_name} | HTTP {status_code} | attempt {attempt}/{MAX_RETRIES} | wait {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            return (
                package_name,
                empty_dependency_block(),
                f"Unexpected HTTP {status_code}",
            )

        except RequestException as exc:
            if attempt >= MAX_RETRIES:
                return (
                    package_name,
                    empty_dependency_block(),
                    f"Network error after {MAX_RETRIES} attempts: {exc}",
                )
            wait_seconds = compute_backoff(attempt)
            print(
                f"[RETRY] [npm_api] | {package_name} | Error: {exc} | attempt {attempt}/{MAX_RETRIES} | wait {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)

        except Exception as exc:
            return package_name, empty_dependency_block(), f"Unexpected error: {exc}"

    return package_name, empty_dependency_block(), "Retries exhausted"


def build_graph(
    package_names: Iterable[str],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    package_list = list(package_names)
    total_packages = len(package_list)

    graph: Dict[str, Dict[str, Dict[str, str]]] = {}
    incidents = 0

    print(
        f"Starting graph construction for {total_packages} packages with {MAX_WORKERS} workers..."
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
                note = f"Error resolving future: {exc}"

            graph[package_name] = dependencies_block

            if note:
                incidents += 1
                print(f"[warn] {package_name}: {note}")

            completed += 1
            if completed % 100 == 0 or completed == total_packages:
                print(
                    f"[PROGRESS] {completed}/{total_packages} ({completed / total_packages:.1%}) | incidents: {incidents}"
                )

    return graph


def save_graph(graph: Dict[str, Dict[str, Dict[str, str]]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(graph, json_file, indent=4)

    print(f"[INFO] File generated: {output_path} | nodes: {len(graph)}")


def main() -> None:
    print("---- [STEP 2] BUILD GRAPH ----")
    started_at = time.time()

    try:
        package_names = read_package_names(INPUT_CSV)
        if not package_names:
            print("[INFO] No packages to process. Aborting execution.")
            return

        graph = build_graph(package_names)
        save_graph(graph, OUTPUT_JSON)

        elapsed = time.time() - started_at
        print(f"[DONE] Process finished in {elapsed:.1f}s | nodes: {len(graph)}")

    except FileNotFoundError as exc:
        print(f"[error] {exc}")
    except ValueError as exc:
        print(f"[error] {exc}")
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
    except Exception as exc:
        print(f"[ERROR] Unhandled failure: {exc}")


if __name__ == "__main__":
    main()
