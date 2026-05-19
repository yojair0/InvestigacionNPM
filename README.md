# NPM Ecosystem Analysis Pipeline

## Purpose

Pipeline to analyze the structural fragility of the NPM ecosystem by selecting packages, building a dependency graph, and calculating infrastructure metrics.

## Methodology

- Work on a closed subset of 5,000 packages.
- Isolate the structural core of the registry to avoid distortions from the periphery.
- Measure `fan_out` and global `fan_in` for each package.
- Identify critical nodes for technical auditing and cascade failure risk analysis.

## Project Structure

```
InvestigacionNPM/
├── pipeline/
│   ├── 0_generate_top10k.py        # Select top 10,000 packages by size
│   ├── 1_filter_popularity.py      # Filter top 5,000 by weekly downloads
│   ├── 2_build_graph.py            # Build dependency graph
│   ├── 3a_calc_fanout.py           # Calculate fan-out for the 5k packages
│   ├── 3b_calc_fanin_global.py     # Calculate global fan-in scanning ~4M packages
│   ├── 4_version_distance.py       # Calculate version distance per dependency
│   └── 5_package_info.py           # Collect detailed package metadata
├── data/
│   ├── raw/                        # Intermediate generated files
│   └── metrics/                    # Final metric outputs
├── docs/
│   └── pipeline_documentation.md
├── run_pipeline.ps1                # Windows orchestrator
└── requirements.txt
```

## Requirements

- Python 3.11+
- Virtual environment in `.venv`
- External dependency: `requests`

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\pip.exe install -r requirements.txt
```

## Running the Pipeline

Run step by step (recommended):

```powershell
# Step 0 - takes several hours, supports pause/resume via checkpoint
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py

# Step 1
.\.venv\Scripts\python.exe pipeline\1_filter_popularity.py

# Step 2
.\.venv\Scripts\python.exe pipeline\2_build_graph.py

# Step 3a - fast, reads from existing graph
.\.venv\Scripts\python.exe pipeline\3a_calc_fanout.py

# Step 3b - takes several hours, supports pause/resume via checkpoint
.\.venv\Scripts\python.exe pipeline\3b_calc_fanin_global.py
```

Run with orchestrator (skips step 0 and 3b if already done):

```powershell
.\run_pipeline.ps1 -SkipTop10k -SkipFanin
```

Test run with limited packages:

```powershell
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py --max-packages 1000
.\.venv\Scripts\python.exe pipeline\3b_calc_fanin_global.py --max-packages 500
```

## Outputs

| File | Location | Description |
|---|---|---|
| `top_10k_by_size.csv` | `data/raw/` | Top 10k packages by unpacked size |
| `top_5k_by_downloads.csv` | `data/raw/` | Top 5k by weekly downloads |
| `dependency_graph.json` | `data/raw/` | Dependencies per package (latest version) |
| `fanout_report.csv` | `data/metrics/` | Fan-out for all 5k packages |
| `fanin_global_report.csv` | `data/metrics/` | Global fan-in scanning ~4M npm packages |
| `version_distance.csv` | `data/metrics/` | Version distance per (package, dependency) pair |
| `packages_info.csv` | `data/metrics/` | Detailed metadata per package (size, files, deps) |

## Methodology Note

- **Fan-out**: total declared dependencies (`dependencies` + `devDependencies`) of each package.
- **Fan-in**: count of how many packages across the full npm catalog depend on each of the 5k packages, separated into `fan_in_prod` (production) and `fan_in_dev` (development).
- Reference version analyzed: `dist-tags.latest` per package.
