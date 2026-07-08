#!/usr/bin/env python3
"""Filters the top 10,000 NPM packages to obtain the 5,000 most popular by downloads."""

from __future__ import annotations

import csv
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

INPUT_CSV = Path("data/raw/top_10k_by_size.csv")
OUTPUT_CSV = Path("data/raw/top_5k_by_downloads.csv")
API_TEMPLATE = "https://api.npmjs.org/downloads/point/last-week/{}"
MAX_WORKERS = 10
MAX_RETRIES = 6
REQUEST_TIMEOUT = 20
TOP_N = 5000
MIN_EXPECTED_INPUT_PACKAGES = 10000

_thread_local = threading.local()


def get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "ucn-msr-npm-popularity-filter/1.0",
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


def read_package_names(csv_path: Path) -> List[str]:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo de entrada: {csv_path}. "
            "Generalo primero con 0_generate_top10k.py"
        )

    package_names: List[str] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "package_name" not in reader.fieldnames:
            raise ValueError(
                "El CSV debe contener una columna llamada 'package_name'."
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


def fetch_downloads(package_name: str) -> Tuple[str, int, Optional[str]]:
    encoded_package_name = quote(package_name, safe="")
    url = API_TEMPLATE.format(encoded_package_name)
    session = get_session()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            status_code = response.status_code

            if status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return package_name, 0, "JSON invalido en API de descargas"

                downloads = payload.get("downloads")
                if isinstance(downloads, int):
                    return package_name, downloads, None
                return package_name, 0, "Campo downloads ausente o invalido"

            if status_code == 404:
                return package_name, 0, "Paquete no encontrado (404)"

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = compute_backoff(attempt, retry_after)
                print(
                    f"[RETRY] [npm_api] | {package_name} | HTTP {status_code} | attempt {attempt}/{MAX_RETRIES} | wait {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            return package_name, 0, f"HTTP inesperado {status_code}"

        except RequestException as exc:
            if attempt >= MAX_RETRIES:
                return package_name, 0, f"Error de red tras {MAX_RETRIES} intentos: {exc}"
            wait_seconds = compute_backoff(attempt)
            print(
                f"[RETRY] [npm_api] | {package_name} | Error: {exc} | attempt {attempt}/{MAX_RETRIES} | wait {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)

        except Exception as exc:
            return package_name, 0, f"Error inesperado: {exc}"

    return package_name, 0, "Se agotaron los reintentos"


def collect_downloads(package_names: Iterable[str]) -> List[Dict[str, int]]:
    package_list = list(package_names)
    total_packages = len(package_list)
    results: List[Dict[str, int]] = []
    incidents = 0

    print(
        f"Starting downloads fetch for {total_packages} packages with {MAX_WORKERS} workers..."
    )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_package = {
            executor.submit(fetch_downloads, package_name): package_name
            for package_name in package_list
        }

        completed = 0
        for future in as_completed(future_to_package):
            package_from_future = future_to_package[future]

            try:
                package_name, downloads, error = future.result()
            except Exception as exc:
                package_name = package_from_future
                downloads = 0
                error = f"Error al resolver future: {exc}"

            if error:
                incidents += 1
                print(f"[warn] {package_name}: {error}")

            results.append({"package_name": package_name, "downloads": downloads})

            completed += 1
            if completed % 100 == 0 or completed == total_packages:
                print(
                    f"[PROGRESS] {completed}/{total_packages} ({completed / total_packages:.1%}) | incidents: {incidents}"
                )

    return results


def save_top_packages(
    package_stats: List[Dict[str, int]], output_path: Path, top_n: int = TOP_N
) -> None:
    sorted_stats = sorted(
        package_stats, key=lambda item: item.get("downloads", 0), reverse=True
    )
    top_packages = sorted_stats[:top_n]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["package_name", "downloads"])
        writer.writeheader()
        writer.writerows(top_packages)

    print(f"File generated: {output_path} | rows: {len(top_packages)}")


def main() -> None:
    print("---- [STEP 1] FILTER POPULARITY ----")
    started_at = time.time()

    try:
        package_names = read_package_names(INPUT_CSV)
        if not package_names:
            print("No packages to process. Aborting execution.")
            return

        if len(package_names) < MIN_EXPECTED_INPUT_PACKAGES:
            raise ValueError(
                "El archivo de entrada tiene menos de 10.000 paquetes unicos. "
                "Esto no cumple el flujo real (10k pesados -> 5k mas descargados)."
            )

        package_stats = collect_downloads(package_names)
        save_top_packages(package_stats, OUTPUT_CSV, TOP_N)

        elapsed = time.time() - started_at
        print(f"[DONE] Process finished in {elapsed:.1f}s | rows: {TOP_N}")

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
