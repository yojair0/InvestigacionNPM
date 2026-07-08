#!/usr/bin/env python3
"""Fetches metadata information (size, files, dependencies) for the 5,000 packages."""

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
DEFAULT_CHECKPOINT_EVERY = 20

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
    print(f"Packages read: {len(names)}")
    return names


def load_checkpoint(path: Path) -> Dict:
    if not path.exists():
        return {"completed": [], "results": []}
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("completed", [])
    state.setdefault("results", [])
    print(f"Checkpoint loaded: {len(state['completed'])} packages already processed")
    return state


def save_checkpoint(path: Path, completed: List[str], results: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "completed": completed,
            "results": results,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f)


def fetch_tarball_stats(tarball_url: str) -> int:
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
                wait = compute_backoff(attempt, parse_retry_after(response.headers.get("Retry-After")))
                print(f"[RETRY] [tarball] | HTTP {response.status_code} | attempt {attempt}/{DEFAULT_MAX_RETRIES} | wait {wait:.1f}s")
                time.sleep(wait)
                continue

            return 0

        except Exception as exc:
            if attempt >= DEFAULT_MAX_RETRIES:
                return 0
            wait = compute_backoff(attempt)
            print(f"[RETRY] [tarball] | Error: {exc} | attempt {attempt}/{DEFAULT_MAX_RETRIES} | wait {wait:.1f}s")
            time.sleep(wait)

    return 0


def fetch_package_info(package_name: str) -> Optional[Dict]:
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
                    "dependencies": json.dumps(deps),
                    "dev_dependencies": json.dumps(dev_deps),
                }

            if status == 404:
                return None

            if status == 429 or 500 <= status < 600:
                wait = compute_backoff(attempt, parse_retry_after(response.headers.get("Retry-After")))
                print(f"[RETRY] [info] | {package_name} | HTTP {status} | attempt {attempt}/{DEFAULT_MAX_RETRIES} | wait {wait:.1f}s")
                time.sleep(wait)
                continue

            return None

        except Exception as exc:
            if attempt >= DEFAULT_MAX_RETRIES:
                return None
            wait = compute_backoff(attempt)
            print(f"[RETRY] [info] | {package_name} | Error: {exc} | attempt {attempt}/{DEFAULT_MAX_RETRIES} | wait {wait:.1f}s")
            time.sleep(wait)

    return None


FIELDNAMES = [
    "package", "npm_link", "version", "size_bytes",
    "file_count", "nonempty_file_count",
    "dependencies", "dev_dependencies",
]


def save_results(results: List[Dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)
    print(f"[INFO] File generated: {output_path} | rows: {len(results)}")


def main() -> None:
    print("---- [STEP 5] PACKAGE INFO ----")
    args = parse_args()
    started_at = time.time()

    packages = load_packages(args.input_csv)

    if args.fresh_start:
        completed: List[str] = []
        results: List[Dict] = []
        print("Fresh start (--fresh-start).")
    else:
        state = load_checkpoint(args.checkpoint)
        completed = state["completed"]
        results = state["results"]

    completed_set = set(completed)
    pending = [p for p in packages if p not in completed_set]
    print(f"Pending: {len(pending)} | Already processed: {len(completed)}")

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
                    print(f"[INFO] Checkpoint saved ({i}/{len(pending)} processed)")

        save_results(results, args.output_csv)
        save_checkpoint(args.checkpoint, completed, results)
        elapsed = time.time() - started_at
        print(f"[DONE] Process finished in {elapsed:.1f}s | packages: {len(results)}")

    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
        save_checkpoint(args.checkpoint, completed, results)
        print("Checkpoint saved. You can resume without losing progress.")

    except Exception as exc:
        print(f"[ERROR] Unhandled failure: {exc}")
        save_checkpoint(args.checkpoint, completed, results)


if __name__ == "__main__":
    main()
