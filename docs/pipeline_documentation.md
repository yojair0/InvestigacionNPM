# NPM Analysis Pipeline Documentation

## 1. Purpose and Methodology
Analyze the structural fragility of the NPM ecosystem by identifying critical infrastructure nodes through its network topology and internal code metrics.
We work with 5,000 packages to avoid peripheral bias. Both network metrics (Fan-Out, Fan-In) and internal code metrics are extracted.

## 2. Pipeline Workflow

**Step 0: Retrieve Top 10k by Size**
(`pipeline/0_generate_top10k.py`): Crawls the paginated NPM catalog and selects the 10,000 largest packages. Uses checkpoints to generate `top_10k_by_size.csv`.

**Step 1: Filter by Popularity**
(`pipeline/1_filter_popularity.py`): Queries the weekly downloads API and filters the previous 10,000 to keep the 5,000 most popular in `top_5k_by_downloads.csv`.

**Step 2: Build Dependency Graph**
(`pipeline/2_build_graph.py`): Extracts dependencies (prod and dev) for the `latest` version of the 5,000 packages, creating `dependency_graph.json`.

**Step 3: Calculate Network Metrics (Fan-Out and Fan-In)**
(`pipeline/3a_calc_fanout.py` and `pipeline/3b_calc_fanin_global.py`): Fan-Out is calculated locally (`fanout_report.csv`) and then ~4M packages in the catalog are scanned to calculate the global Fan-In towards our target packages (`fanin_global_report.csv`).

**Step 4: Version Distance**
(`pipeline/4_version_distance.py`): Evaluates the version divergence between what is declared and what is available, saving the results in `version_distance.csv`.

**Step 5: Metadata Extraction**
(`pipeline/5_package_info.py`): Collects additional metadata (size, file count) and produces `packages_info.csv`.

**Step 6: Internal Metrics Extraction (AST)**
(`pipeline/6_ extract_inner_metrics_jt.js` and `jt_worker.js`): Temporarily downloads the source code of the packages and calculates internal metrics in parallel with `jtmetrics`, outputting `inner_metrics_jt.ndjson`.

## 3. Generated Deliverables
- `top_10k_by_size.csv`
- `top_5k_by_downloads.csv`
- `dependency_graph.json`
- `fanout_report.csv`
- `fanin_global_report.csv`
- `version_distance.csv`
- `packages_info.csv`
- `inner_metrics_jt.ndjson`

## 4. Pipeline Execution

Complete execution using the orchestrator:
```powershell
.\run_pipeline.ps1 -FreshStart
```

Execution skipping the most expensive steps (if previously completed):
```powershell
.\run_pipeline.ps1 -SkipExtractLargestPackages -SkipCalculateGlobalFanIn
```

Run only internal metrics collection:
```powershell
.\run_pipeline.ps1 -RunOnlyExtractInternalMetrics
```

Run a test limiting resources (Workers, Pagination, Package limit):
```powershell
.\run_pipeline.ps1 -RunOnlyCalculateGlobalFanIn -MaxPackagesLimit 500 -WorkersCount 5
```

Execute individual stages manually (without the orchestrator):
```powershell
.\.venv\Scripts\python.exe pipeline\0_generate_top10k.py --workers 10
.\.venv\Scripts\python.exe pipeline\1_filter_popularity.py
.\.venv\Scripts\python.exe pipeline\2_build_graph.py
.\.venv\Scripts\python.exe pipeline\3a_calc_fanout.py
.\.venv\Scripts\python.exe pipeline\3b_calc_fanin_global.py --workers 10 --max-packages 500
node "pipeline\6_ extract_inner_metrics_jt.js"
```
