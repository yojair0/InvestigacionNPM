#!/usr/bin/env python3
"""Genera el top 10.000 de paquetes NPM por tamano en bytes.

Estrategia:
1. Recorre el catalogo de paquetes via replicate.npmjs.com/_all_docs.
2. Para cada paquete consulta registry.npmjs.org/{paquete}/latest.
3. Extrae dist.unpackedSize (fallback: dist.size).
4. Mantiene un heap minimo para conservar solo los N paquetes mas pesados.
5. Guarda checkpoint periodico para reanudar sin perder avance.
"""

from __future__ import annotations

import argparse
import csv
import heapq
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
    raise SystemExit(
        "Dependencia faltante: requests. Instala con: pip install requests"
    ) from exc

REPLICATE_ALL_DOCS_URL = "https://replicate.npmjs.com/_all_docs"
PACKAGE_LATEST_URL_TEMPLATE = "https://registry.npmjs.org/{}/latest"

DEFAULT_OUTPUT_CSV = Path("data/raw/top_10k_by_size.csv")
DEFAULT_CHECKPOINT = Path("data/raw/checkpoint_top10k.json")

DEFAULT_TOP_N = 10_000
DEFAULT_WORKERS = 10
DEFAULT_PAGE_SIZE = 300
DEFAULT_MAX_RETRIES = 6
DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_PROGRESS_EVERY = 500
DEFAULT_CHECKPOINT_EVERY_PAGES = 5

_thread_local = threading.local()


def parse_args() -> argparse.Namespace:
    """Parsea argumentos de linea de comandos para controlar la extraccion."""
    parser = argparse.ArgumentParser(
        description=(
            "Genera top_10k_pesados.csv recorriendo paquetes NPM y midiendo tamano por bytes."
        )
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Ruta del CSV de salida (default: top_10k_by_size.csv).",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT,
        help="Ruta del archivo checkpoint para reanudar ejecucion.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Cantidad de paquetes pesados a conservar (default: 10000).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Numero de workers concurrentes para consultar /latest.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Tamano de pagina para _all_docs (default: 300).",
    )
    parser.add_argument(
        "--max-packages",
        type=int,
        default=None,
        help="Limite opcional de paquetes a escanear (solo para pruebas).",
    )
    parser.add_argument(
        "--fresh-start",
        action="store_true",
        help="Ignora checkpoint previo y comienza desde cero.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=DEFAULT_PROGRESS_EVERY,
        help="Frecuencia de log de progreso por paquetes procesados.",
    )
    return parser.parse_args()


def get_thread_session() -> requests.Session:
    """Crea o reutiliza una sesion HTTP por hilo para mejorar rendimiento."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "ucn-msr-npm-heavy-topk-builder/1.0",
            }
        )
        _thread_local.session = session
    return _thread_local.session


def parse_retry_after(retry_after_value: Optional[str]) -> Optional[float]:
    """Convierte la cabecera Retry-After a segundos, cuando es valida."""
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


def load_checkpoint(checkpoint_path: Path) -> Dict[str, object]:
    """Carga checkpoint si existe; si no, retorna estado inicial."""
    if not checkpoint_path.exists():
        return {
            "last_doc_id": None,
            "processed": 0,
            "with_size": 0,
            "missing_size": 0,
            "incidents": 0,
            "page_number": 0,
            "heap": [],
        }

    with checkpoint_path.open("r", encoding="utf-8") as checkpoint_file:
        checkpoint = json.load(checkpoint_file)

    checkpoint.setdefault("last_doc_id", None)
    checkpoint.setdefault("processed", 0)
    checkpoint.setdefault("with_size", 0)
    checkpoint.setdefault("missing_size", 0)
    checkpoint.setdefault("incidents", 0)
    checkpoint.setdefault("page_number", 0)
    checkpoint.setdefault("heap", [])
    return checkpoint


def save_checkpoint(
    checkpoint_path: Path,
    last_doc_id: Optional[str],
    processed: int,
    with_size: int,
    missing_size: int,
    incidents: int,
    page_number: int,
    heap: List[Tuple[int, str, str]],
) -> None:
    """Guarda estado parcial para poder reanudar ejecuciones largas."""
    payload = {
        "last_doc_id": last_doc_id,
        "processed": processed,
        "with_size": with_size,
        "missing_size": missing_size,
        "incidents": incidents,
        "page_number": page_number,
        "heap": [[size_bytes, package_name, source] for size_bytes, package_name, source in heap],
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.open("w", encoding="utf-8") as checkpoint_file:
        json.dump(payload, checkpoint_file, indent=4)


def fetch_package_ids_page(
    start_after_doc_id: Optional[str],
    page_size: int,
    max_retries: int,
    timeout: int,
) -> Tuple[List[str], Optional[str]]:
    """Obtiene una pagina de IDs de paquetes desde replicate._all_docs con retries."""
    session = get_thread_session()

    params: Dict[str, object] = {
        "limit": page_size,
    }

    if start_after_doc_id is not None:
        params["startkey"] = json.dumps(start_after_doc_id)

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                REPLICATE_ALL_DOCS_URL,
                params=params,
                timeout=timeout,
            )
            status_code = response.status_code

            if status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    raise RuntimeError("Respuesta JSON invalida en _all_docs")

                rows = payload.get("rows")
                if not isinstance(rows, list):
                    raise RuntimeError("Respuesta inesperada: rows ausente o invalido")

                package_ids: List[str] = []
                next_doc_id: Optional[str] = None

                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    doc_id = row.get("id")
                    if not isinstance(doc_id, str) or not doc_id:
                        continue
                    next_doc_id = doc_id

                    # startkey es inclusivo: se descarta el primer ID repetido del cursor previo.
                    if start_after_doc_id is not None and doc_id == start_after_doc_id:
                        continue

                    if doc_id.startswith("_design/"):
                        continue
                    package_ids.append(doc_id)

                return package_ids, next_doc_id

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = compute_backoff(attempt, retry_after)
                print(
                    f"[retry all_docs] HTTP {status_code} | intento {attempt}/{max_retries} | espera {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            raise RuntimeError(f"HTTP inesperado en _all_docs: {status_code}")

        except RequestException as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Error de red en _all_docs tras {max_retries} intentos: {exc}"
                ) from exc
            wait_seconds = compute_backoff(attempt)
            print(
                f"[retry all_docs] error de red: {exc} | intento {attempt}/{max_retries} | espera {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)


def extract_size_bytes(latest_payload: Dict[str, object]) -> Tuple[int, str]:
    """Extrae tamano en bytes desde dist.unpackedSize o fallback dist.size."""
    dist = latest_payload.get("dist")
    if isinstance(dist, dict):
        unpacked_size = dist.get("unpackedSize")
        if isinstance(unpacked_size, int) and unpacked_size > 0:
            return unpacked_size, "dist.unpackedSize"

        packed_size = dist.get("size")
        if isinstance(packed_size, int) and packed_size > 0:
            return packed_size, "dist.size"

    return 0, "missing"


def fetch_package_size(
    package_name: str,
    max_retries: int,
    timeout: int,
) -> Tuple[str, int, str, Optional[str]]:
    """Consulta /latest y retorna tamano en bytes para un paquete con retries."""
    session = get_thread_session()
    encoded_name = quote(package_name, safe="")
    url = PACKAGE_LATEST_URL_TEMPLATE.format(encoded_name)

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            status_code = response.status_code

            if status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return package_name, 0, "missing", "JSON invalido"

                size_bytes, source = extract_size_bytes(payload)
                if size_bytes > 0:
                    return package_name, size_bytes, source, None
                return package_name, 0, source, "Sin tamano disponible"

            if status_code == 404:
                return package_name, 0, "missing", "Paquete no encontrado (404)"

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = compute_backoff(attempt, retry_after)
                print(
                    f"[retry latest] {package_name} | HTTP {status_code} | intento {attempt}/{max_retries} | espera {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            return package_name, 0, "missing", f"HTTP inesperado {status_code}"

        except RequestException as exc:
            if attempt >= max_retries:
                return (
                    package_name,
                    0,
                    "missing",
                    f"Error de red tras {max_retries} intentos: {exc}",
                )
            wait_seconds = compute_backoff(attempt)
            print(
                f"[retry latest] {package_name} | error de red: {exc} | intento {attempt}/{max_retries} | espera {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)

        except Exception as exc:
            return package_name, 0, "missing", f"Error inesperado: {exc}"

    return package_name, 0, "missing", "Se agotaron los reintentos"


def keep_top_heavy(
    heap: List[Tuple[int, str, str]],
    top_n: int,
    package_name: str,
    size_bytes: int,
    source: str,
) -> None:
    """Mantiene un heap minimo con los top_n paquetes de mayor tamano."""
    if size_bytes <= 0:
        return

    item = (size_bytes, package_name, source)

    if len(heap) < top_n:
        heapq.heappush(heap, item)
        return

    smallest = heap[0]
    if item > smallest:
        heapq.heapreplace(heap, item)


def write_top_csv(
    heap: List[Tuple[int, str, str]],
    output_csv: Path,
    top_n: int,
) -> None:
    """Escribe CSV final ordenado descendente por bytes."""
    sorted_rows = sorted(heap, key=lambda item: item[0], reverse=True)[:top_n]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["package_name", "size_bytes", "size_source"],
        )
        writer.writeheader()
        for size_bytes, package_name, source in sorted_rows:
            writer.writerow(
                {
                    "package_name": package_name,
                    "size_bytes": size_bytes,
                    "size_source": source,
                }
            )

    print(f"CSV final generado: {output_csv} | filas: {len(sorted_rows)}")


def main() -> None:
    """Orquesta exploracion del registro NPM y construye top 10k por bytes."""
    args = parse_args()
    started_at = time.time()

    if args.top_n <= 0:
        raise SystemExit("--top-n debe ser mayor a 0")
    if args.page_size <= 0:
        raise SystemExit("--page-size debe ser mayor a 0")
    if args.workers <= 0:
        raise SystemExit("--workers debe ser mayor a 0")

    if args.fresh_start:
        state = {
            "last_doc_id": None,
            "processed": 0,
            "with_size": 0,
            "missing_size": 0,
            "incidents": 0,
            "page_number": 0,
            "heap": [],
        }
        print("Inicio limpio solicitado (--fresh-start).")
    else:
        state = load_checkpoint(args.checkpoint)
        if state.get("processed", 0) > 0:
            print(
                "Reanudando desde checkpoint: "
                f"procesados={state.get('processed', 0)}, "
                f"ultima_clave={state.get('last_doc_id')}"
            )

    last_doc_id = state.get("last_doc_id")
    processed = int(state.get("processed", 0))
    with_size = int(state.get("with_size", 0))
    missing_size = int(state.get("missing_size", 0))
    incidents = int(state.get("incidents", 0))
    page_number = int(state.get("page_number", 0))

    restored_heap_raw = state.get("heap", [])
    heap: List[Tuple[int, str, str]] = []
    if isinstance(restored_heap_raw, list):
        for item in restored_heap_raw:
            if (
                isinstance(item, list)
                and len(item) == 3
                and isinstance(item[0], int)
                and isinstance(item[1], str)
                and isinstance(item[2], str)
            ):
                heap.append((item[0], item[1], item[2]))
    heapq.heapify(heap)

    print(
        "Inicio de extraccion real para top pesados. "
        "Este proceso puede tardar bastante (escaneo amplio del registro NPM)."
    )

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while True:
                if args.max_packages is not None and processed >= args.max_packages:
                    print(
                        f"Se alcanzo el limite maximo de prueba (--max-packages={args.max_packages})."
                    )
                    break

                package_ids, next_doc_id = fetch_package_ids_page(
                    start_after_doc_id=last_doc_id,
                    page_size=args.page_size,
                    max_retries=DEFAULT_MAX_RETRIES,
                    timeout=DEFAULT_REQUEST_TIMEOUT,
                )

                if not package_ids:
                    print("No hay mas paquetes por leer desde _all_docs.")
                    break

                if args.max_packages is not None:
                    remaining = args.max_packages - processed
                    if remaining <= 0:
                        break
                    package_ids = package_ids[:remaining]

                page_number += 1
                print(
                    f"Pagina {page_number}: {len(package_ids)} paquetes para medir tamano (cursor={next_doc_id})"
                )

                futures = [
                    executor.submit(
                        fetch_package_size,
                        package_name,
                        DEFAULT_MAX_RETRIES,
                        DEFAULT_REQUEST_TIMEOUT,
                    )
                    for package_name in package_ids
                ]

                for future in as_completed(futures):
                    package_name, size_bytes, source, note = future.result()

                    keep_top_heavy(heap, args.top_n, package_name, size_bytes, source)

                    processed += 1
                    if size_bytes > 0:
                        with_size += 1
                    else:
                        missing_size += 1

                    if note:
                        incidents += 1

                    if processed % args.progress_every == 0:
                        threshold = heap[0][0] if heap else 0
                        print(
                            "Progreso: "
                            f"procesados={processed}, "
                            f"con_tamano={with_size}, "
                            f"sin_tamano={missing_size}, "
                            f"incidencias={incidents}, "
                            f"umbral_heap={threshold}"
                        )

                last_doc_id = next_doc_id

                if page_number % DEFAULT_CHECKPOINT_EVERY_PAGES == 0:
                    save_checkpoint(
                        checkpoint_path=args.checkpoint,
                        last_doc_id=last_doc_id,
                        processed=processed,
                        with_size=with_size,
                        missing_size=missing_size,
                        incidents=incidents,
                        page_number=page_number,
                        heap=heap,
                    )
                    print(f"Checkpoint guardado en {args.checkpoint}")

                if next_doc_id is None:
                    print("Cursor final detectado. Fin del escaneo.")
                    break

        write_top_csv(heap, args.output_csv, args.top_n)

        save_checkpoint(
            checkpoint_path=args.checkpoint,
            last_doc_id=last_doc_id,
            processed=processed,
            with_size=with_size,
            missing_size=missing_size,
            incidents=incidents,
            page_number=page_number,
            heap=heap,
        )

        elapsed = time.time() - started_at
        print(
            "Proceso completado. "
            f"Procesados={processed}, con_tamano={with_size}, sin_tamano={missing_size}, "
            f"incidencias={incidents}, tiempo={elapsed:.1f}s"
        )

    except KeyboardInterrupt:
        print("\nInterrupcion detectada, guardando checkpoint...")
        save_checkpoint(
            checkpoint_path=args.checkpoint,
            last_doc_id=last_doc_id,
            processed=processed,
            with_size=with_size,
            missing_size=missing_size,
            incidents=incidents,
            page_number=page_number,
            heap=heap,
        )
        print(f"Checkpoint guardado en {args.checkpoint}")
    except Exception as exc:
        print(f"[error] Fallo no controlado: {exc}")
        save_checkpoint(
            checkpoint_path=args.checkpoint,
            last_doc_id=last_doc_id,
            processed=processed,
            with_size=with_size,
            missing_size=missing_size,
            incidents=incidents,
            page_number=page_number,
            heap=heap,
        )
        print(f"Checkpoint guardado en {args.checkpoint}")


if __name__ == "__main__":
    main()
