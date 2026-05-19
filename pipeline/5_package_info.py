#!/usr/bin/env python3
"""Recopila informacion detallada de los 5k paquetes NPM.

Para cada paquete obtiene desde el registry: nombre, link, version latest,
tamano en bytes, conteo de archivos (total y no vacios), dependencias y
devDependencies con sus versiones declaradas.

El conteo de archivos no vacios requiere descargar el tarball en memoria
y contar los miembros con size > 0.

Entrada:  data/raw/top_5k_by_downloads.csv
Salida:   data/metrics/packages_info.csv
"""

from __future__ import annotations

import argparse
import io
import json
import random
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

try:
    import requests
except ImportError as exc:
    raise SystemExit("Dependencia faltante: instala con: pip install requests") from exc

import csv

REGISTRY_LATEST_TEMPLATE = "https://registry.npmjs.org/{}/latest"
NPM_LINK_TEMPLATE = "https://www.npmjs.com/package/{}"

DEFAULT_INPUT_CSV = Path("data/raw/top_5k_by_downloads.csv")
DEFAULT_OUTPUT_CSV = Path("data/metrics/packages_info.csv")
DEFAULT_CHECKPOINT = Path("data/raw/checkpoint_package_info.json")

DEFAULT_WORKERS = 10
DEFAULT_MAX_RETRIES = 5
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_CHECKPOINT_EVERY = 100

_thread_local = threading.local()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recopila informacion detallada de los 5k paquetes NPM."
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--fresh-start", action="store_true",
                        help="Ignora checkpoint previo y empieza desde cero.")
    return parser.parse_args()


def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({"Accept": "application/json",
                           "User-Agent": "npm-package-info/1.0"})
        _thread_local.session = s
    return _thread_local.session


def compute_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    if retry_after is not None:
        return min(max(retry_after, 1.0), 120.0)
    return min((2 ** (attempt - 1)) + random.uniform(0.0, 0.5), 60.0)


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def load_packages(csv_path: Path) -> List[str]:
    """Carga la lista ordenada de paquetes desde el CSV de los 5k."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No se encontro: {csv_path}. Generalo con 1_filter_popularity.py"
        )
    names: List[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("package_name") or "").strip()
            if name:
                names.append(name)
    print(f"Paquetes a procesar: {len(names)}")
    return names


def load_checkpoint(path: Path) -> Dict:
    """Carga checkpoint si existe, sino retorna estado inicial."""
    if not path.exists():
        return {"completed": [], "results": []}
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("completed", [])
    state.setdefault("results", [])
    print(f"Checkpoint cargado: {len(state['completed'])} paquetes ya procesados")
    return state


def save_checkpoint(path: Path, completed: List[str], results: List[Dict]) -> None:
    """Guarda el progreso actual en el archivo de checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "completed": completed,
            "results": results,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f)


def fetch_tarball_stats(tarball_url: str) -> int:
    """Descarga el .tgz en memoria y retorna el conteo de archivos con size > 0."""
    session = get_session()

    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            response = session.get(tarball_url, timeout=DEFAULT_REQUEST_TIMEOUT)
            if response.status_code == 200:
                try:
                    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
                        return sum(1 for m in tar.getmembers() if m.isfile() and m.size > 0)
                except tarfile.TarError:
                    return 0

            if response.status_code == 429 or 500 <= response.status_code < 600:
                time.sleep(compute_backoff(attempt, parse_retry_after(
                    response.headers.get("Retry-After"))))
                continue

            return 0

        except Exception:
            if attempt >= DEFAULT_MAX_RETRIES:
                return 0
            time.sleep(compute_backoff(attempt))

    return 0


def fetch_package_info(package_name: str) -> Optional[Dict]:
    """Consulta /latest y descarga el tarball para construir la fila del CSV."""
    session = get_session()
    url = REGISTRY_LATEST_TEMPLATE.format(quote(package_name, safe=""))

    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            status = response.status_code

            if status == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return None

                dist = payload.get("dist") or {}
                deps = payload.get("dependencies") or {}
                dev_deps = payload.get("devDependencies") or {}
                tarball_url = dist.get("tarball", "")

                nonempty = fetch_tarball_stats(tarball_url) if tarball_url else 0

                return {
                    "package": package_name,
                    "npm_link": NPM_LINK_TEMPLATE.format(package_name),
                    "version": payload.get("version", ""),
                    "size_bytes": dist.get("unpackedSize", 0),
                    "file_count": dist.get("fileCount", 0),
                    "nonempty_file_count": nonempty,
                    "dep_count": len(deps),
                    "dev_dep_count": len(dev_deps),
                    "dependencies": json.dumps(deps),
                    "dev_dependencies": json.dumps(dev_deps),
                }

            if status == 404:
                return None

            if status == 429 or 500 <= status < 600:
                time.sleep(compute_backoff(attempt, parse_retry_after(
                    response.headers.get("Retry-After"))))
                continue

            return None

        except Exception:
            if attempt >= DEFAULT_MAX_RETRIES:
                return None
            time.sleep(compute_backoff(attempt))

    return None


FIELDNAMES = [
    "package", "npm_link", "version", "size_bytes",
    "file_count", "nonempty_file_count",
    "dep_count", "dev_dep_count",
    "dependencies", "dev_dependencies",
]


def save_results(results: List[Dict], output_path: Path) -> None:
    """Guarda el CSV final con todos los paquetes procesados."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV generado: {output_path} | filas: {len(results)}")


def main() -> None:
    """Orquesta la recopilacion de informacion de los 5k paquetes."""
    args = parse_args()
    started_at = time.time()

    packages = load_packages(args.input_csv)

    if args.fresh_start:
        completed: List[str] = []
        results: List[Dict] = []
        print("Inicio limpio (--fresh-start).")
    else:
        state = load_checkpoint(args.checkpoint)
        completed = state["completed"]
        results = state["results"]

    completed_set = set(completed)
    pending = [p for p in packages if p not in completed_set]
    print(f"Pendientes: {len(pending)} | Ya procesados: {len(completed)}")

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_package_info, pkg): pkg for pkg in pending}

            for i, future in enumerate(as_completed(futures), start=1):
                pkg = futures[future]
                try:
                    row = future.result()
                except Exception:
                    row = None

                if row:
                    results.append(row)
                completed.append(pkg)

                if i % DEFAULT_CHECKPOINT_EVERY == 0:
                    save_checkpoint(args.checkpoint, completed, results)
                    print(f"Checkpoint guardado ({i}/{len(pending)} procesados)")

        save_results(results, args.output_csv)
        save_checkpoint(args.checkpoint, completed, results)
        elapsed = time.time() - started_at
        print(f"Proceso finalizado en {elapsed:.1f}s | paquetes: {len(results)}")

    except KeyboardInterrupt:
        print("\nPausa solicitada. Guardando checkpoint...")
        save_checkpoint(args.checkpoint, completed, results)
        print("Checkpoint guardado. Puedes reanudar sin perder avance.")

    except Exception as exc:
        print(f"[error] {exc}")
        save_checkpoint(args.checkpoint, completed, results)


if __name__ == "__main__":
    main()
