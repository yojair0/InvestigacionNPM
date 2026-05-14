# NPM Ecosystem Analysis Pipeline

## Purpose

Pipeline to analyze the structural fragility of the NPM ecosystem by selecting packages, building a dependency graph, and calculating infrastructure metrics.

## Methodology

- Work on a closed subset of 5,000 packages.
- Isolate the structural core of the registry to avoid distortions from the periphery.
- Measure `fan_in`, `fan_out`, and `risk_score` on the internal graph of the subset.
- Identify critical nodes for technical auditing and cascade failure risk analysis.

## Project Structure

```
InvestigacionNPM/
├── pipeline/
│   ├── 0_generate_top10k.py       # Select top 10,000 packages by size
│   ├── 1_filter_popularity.py     # Filter top 5,000 by weekly downloads
│   ├── 2_build_graph.py           # Build dependency graph
│   └── 3_calc_fanin_fanout.py     # Calculate fan-in/out metrics (all 5k packages)
├── data/
│   ├── raw/                       # Intermediate generated files
│   └── metrics/                   # Final metric outputs
├── docs/
│   └── pipeline_documentation.md
├── run_pipeline.ps1               # Windows orchestrator
└── requirements.txt
```

## Requirements

- Python 3.11+
- Virtual environment in `.venv`
- External dependency: `requests`

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Running the Pipeline

Run step by step (recommended):

```powershell
# Step 0 - takes several hours, can be paused and resumed
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py

# Step 1
.\.venv\Scripts\python.exe pipeline\1_filter_popularity.py

# Step 2
.\.venv\Scripts\python.exe pipeline\2_build_graph.py

# Step 3
.\.venv\Scripts\python.exe pipeline\3_calc_fanin_fanout.py
```

Run steps 1-2 (skipping step 0 if already done):

```powershell
.\run_pipeline.ps1 -SkipTop10k
```

Test run with limited packages:

```powershell
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py --max-packages 1000
```

## Outputs

| File | Location | Description |
|---|---|---|
| `top_10k_by_size.csv` | `data/raw/` | Top 10k packages by unpacked size |
| `top_5k_by_downloads.csv` | `data/raw/` | Top 5k by weekly downloads |
| `dependency_graph.json` | `data/raw/` | Dependencies per package |
| `fanin_fanout_report.csv` | `data/metrics/` | Fan-in/out metrics for all 5k packages |

## Methodology Note

- `fan_in` is calculated both within the 5k subset and globally (packages outside the 5k that depend on them).
- Reference version analyzed: `dist-tags.latest` per package.
