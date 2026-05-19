#!/usr/bin/env python3
"""Calcula fan-in global de los 5k paquetes NPM recorriendo todo el catalogo.

Recorre ~4M paquetes via replicate.npmjs.com/_all_docs, consulta sus dependencias
y cuenta cuantas veces cada uno de los 5k paquetes objetivo es referenciado.

Separado en:
  - fan_in_prod: referencias desde 'dependencies' (produccion)
  - fan_in_dev:  referencias desde 'devDependencies' (desarrollo)

Entrada:  data/raw/top_5k_by_downloads.csv
Salida:   data/metrics/fanin_global_report.csv
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
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote

try:
    import requests
    from requests.exceptions import RequestException
except ImportError as exc:
    raise SystemExit("Dependencia faltante: instala con: pip install requests") from exc

REPLICATE_ALL_DOCS_URL = "https://replicate.npmjs.com/_all_docs"
REGISTRY_LATEST_TEMPLATE = "https://registry.npmjs.org/{}/latest"

DEFAULT_INPUT_CSV = Path("data/raw/top_5k_by_downloads.csv")
DEFAULT_OUTPUT_CSV = Path("data/metrics/fanin_global_report.csv")
DEFAULT_CHECKPOINT = Path("data/raw/checkpoint_fanin_global.json")

DEFAULT_WORKERS = 10
DEFAULT_PAGE_SIZE = 300
DEFAULT_MAX_RETRIES = 6
DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_PROGRESS_EVERY = 5000
DEFAULT_CHECKPOINT_EVERY_PAGES = 5

_thread_local = threading.local()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calcula fan-in global de los 5k paquetes NPM (~4M paquetes a escanear)."
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-packages", type=int, default=None,
                        help="Limite de paquetes a escanear (solo para pruebas).")
    parser.add_argument("--fresh-start", action="store_true",
                        help="Ignora checkpoint previo y empieza desde cero.")
    return parser.parse_args()

def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({"Accept": "application/json",
                           "User-Agent": "npm-fanin-global-scanner/1.0"})
        _thread_local.session = s
    return _thread_local.session


def compute_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    if retry_after is not None:
        return min(max(retry_after, 1.0), 120.0)
    return min((2 ** (attempt - 1)) + random.uniform(0.0, 0.5), 120.0)


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def load_target_packages(csv_path: Path) -> Set[str]:
    """Carga los 5k paquetes objetivo en un Set para busqueda O(1)."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No se encontro: {csv_path}. Generalo con 1_filter_popularity.py"
        )
    names: Set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("package_name") or "").strip()
            if name:
                names.add(name)
    print(f"Paquetes objetivo cargados: {len(names)}")
    return names


def load_checkpoint(path: Path) -> Dict:
    if not path.exists():
        return {"last_doc_id": None, "processed": 0, "page_number": 0,
                "counters_prod": {}, "counters_dev": {}}
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("last_doc_id", None)
    state.setdefault("processed", 0)
    state.setdefault("page_number", 0)
    state.setdefault("counters_prod", {})
    state.setdefault("counters_dev", {})
    return state


def save_checkpoint(path: Path, last_doc_id: Optional[str], processed: int,
                    page_number: int, counters_prod: Dict, counters_dev: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "last_doc_id": last_doc_id,
            "processed": processed,
            "page_number": page_number,
            "counters_prod": counters_prod,
            "counters_dev": counters_dev,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)


def fetch_page_ids(
    start_after: Optional[str],
    page_size: int,
) -> Tuple[List[str], Optional[str]]:
    """Obtiene una pagina de IDs de paquetes desde replicate._all_docs."""
    session = get_session()
    params: Dict = {"limit": page_size}
    if start_after is not None:
        params["startkey"] = json.dumps(start_after)

    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            response = session.get(REPLICATE_ALL_DOCS_URL, params=params,
                                   timeout=DEFAULT_REQUEST_TIMEOUT)
            status = response.status_code

            if status == 200:
                rows = response.json().get("rows", [])
                ids: List[str] = []
                next_id: Optional[str] = None
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    doc_id = row.get("id")
                    if not isinstance(doc_id, str) or not doc_id:
                        continue
                    next_id = doc_id
                    if start_after is not None and doc_id == start_after:
                        continue
                    if doc_id.startswith("_design/"):
                        continue
                    ids.append(doc_id)
                return ids, next_id

            if status == 429 or 500 <= status < 600:
                wait = compute_backoff(attempt, parse_retry_after(
                    response.headers.get("Retry-After")))
                print(f"[retry all_docs] HTTP {status} | intento {attempt} | espera {wait:.1f}s")
                time.sleep(wait)
                continue

            raise RuntimeError(f"HTTP inesperado en _all_docs: {status}")

        except RequestException as exc:
            if attempt >= DEFAULT_MAX_RETRIES:
                raise RuntimeError(f"Error de red en _all_docs: {exc}") from exc
            time.sleep(compute_backoff(attempt))

    return [], None


def fetch_package_deps(package_name: str) -> Tuple[str, Set[str], Set[str]]:
    """Consulta /latest y retorna (nombre, prod_deps, dev_deps)."""
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
                    return package_name, set(), set()
                deps = payload.get("dependencies")
                dev_deps = payload.get("devDependencies")
                return (
                    package_name,
                    set(deps.keys()) if isinstance(deps, dict) else set(),
                    set(dev_deps.keys()) if isinstance(dev_deps, dict) else set(),
                )

            if status == 404:
                return package_name, set(), set()

            if status == 429 or 500 <= status < 600:
                wait = compute_backoff(attempt, parse_retry_after(
                    response.headers.get("Retry-After")))
                print(f"[retry deps] {package_name} | HTTP {status} | intento {attempt} | espera {wait:.1f}s")
                time.sleep(wait)
                continue

            return package_name, set(), set()

        except Exception as exc:
            if attempt >= DEFAULT_MAX_RETRIES:
                return package_name, set(), set()
            wait = compute_backoff(attempt)
            print(f"[retry deps] {package_name} | error de red: {exc} | intento {attempt} | espera {wait:.1f}s")
            time.sleep(wait)

    return package_name, set(), set()


def save_results(counters_prod: Dict[str, int], counters_dev: Dict[str, int],
                 target_packages: Set[str], output_path: Path) -> None:
    """Guarda el reporte final de fan-in global en CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for pkg in sorted(target_packages):
        prod = counters_prod.get(pkg, 0)
        dev = counters_dev.get(pkg, 0)
        rows.append({"package": pkg, "fan_in_prod": prod,
                     "fan_in_dev": dev, "fan_in_total": prod + dev})

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["package", "fan_in_prod", "fan_in_dev", "fan_in_total"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV generado: {output_path} | filas: {len(rows)}")


def main() -> None:
    """Orquesta el escaneo global del catalogo NPM para calcular fan-in."""
    args = parse_args()
    started_at = time.time()

    target_packages = load_target_packages(args.input_csv)

    if args.fresh_start:
        state: Dict = {"last_doc_id": None, "processed": 0, "page_number": 0,
                       "counters_prod": {}, "counters_dev": {}}
        print("Inicio limpio solicitado (--fresh-start).")
    else:
        state = load_checkpoint(args.checkpoint)
        if state["processed"] > 0:
            print(f"Reanudando desde checkpoint: procesados={state['processed']}, "
                  f"pagina={state['page_number']}")

    last_doc_id: Optional[str] = state["last_doc_id"]
    processed: int = state["processed"]
    page_number: int = state["page_number"]
    counters_prod: Dict[str, int] = state["counters_prod"]
    counters_dev: Dict[str, int] = state["counters_dev"]

    print("Iniciando escaneo global. Usa Ctrl+C para pausar y reanudar luego.")

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while True:
                if args.max_packages is not None and processed >= args.max_packages:
                    print(f"Limite de prueba alcanzado (--max-packages={args.max_packages}).")
                    break

                page_ids, next_doc_id = fetch_page_ids(last_doc_id, args.page_size)

                if not page_ids:
                    print("No hay mas paquetes. Escaneo completo.")
                    break

                if args.max_packages is not None:
                    page_ids = page_ids[:args.max_packages - processed]

                page_number += 1
                print(f"Procesando página {page_number} ({len(page_ids)} paquetes) | Total procesados hasta ahora: {processed:,}")

                futures = {
                    executor.submit(fetch_package_deps, pkg_id): pkg_id
                    for pkg_id in page_ids
                }

                for future in as_completed(futures):
                    try:
                        pkg_name, prod_deps, dev_deps = future.result()
                    except Exception:
                        processed += 1
                        continue

                    for dep in prod_deps:
                        if dep in target_packages:
                            counters_prod[dep] = counters_prod.get(dep, 0) + 1
                    for dep in dev_deps:
                        if dep in target_packages:
                            counters_dev[dep] = counters_dev.get(dep, 0) + 1

                    processed += 1
                    if processed % 50 == 0:
                        print(f"  -> {processed:,} paquetes procesados...")
                    if processed % DEFAULT_PROGRESS_EVERY == 0:
                        print(f"Progreso: {processed:,} paquetes escaneados "
                              f"(pagina {page_number})")

                last_doc_id = next_doc_id

                if page_number % DEFAULT_CHECKPOINT_EVERY_PAGES == 0:
                    save_checkpoint(args.checkpoint, last_doc_id, processed,
                                    page_number, counters_prod, counters_dev)
                    print(f"Checkpoint guardado (pagina {page_number})")

                if next_doc_id is None:
                    print("Cursor final detectado. Fin del escaneo.")
                    break

        save_results(counters_prod, counters_dev, target_packages, args.output_csv)
        save_checkpoint(args.checkpoint, last_doc_id, processed, page_number,
                        counters_prod, counters_dev)

        elapsed = time.time() - started_at
        print(f"Proceso finalizado en {elapsed:.1f}s | escaneados: {processed:,}")

    except KeyboardInterrupt:
        print("\nPausa solicitada. Guardando checkpoint...")
        save_checkpoint(args.checkpoint, last_doc_id, processed, page_number,
                        counters_prod, counters_dev)
        print(f"Checkpoint guardado. Puedes reanudar sin perder avance.")

    except Exception as exc:
        print(f"[error] Falla no controlada: {exc}")
        save_checkpoint(args.checkpoint, last_doc_id, processed, page_number,
                        counters_prod, counters_dev)


if __name__ == "__main__":
    main()
