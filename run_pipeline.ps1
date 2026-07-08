param(
    [switch]$FreshStart,
    [switch]$SkipExtractLargestPackages,
    [switch]$SkipCalculateGlobalFanIn,
    [switch]$SkipExtractInternalMetrics,
    [switch]$RunOnlyExtractLargestPackages,
    [switch]$RunOnlyFilterMostDownloaded,
    [switch]$RunOnlyBuildDependencyGraph,
    [switch]$RunOnlyCalculateFanOut,
    [switch]$RunOnlyCalculateGlobalFanIn,
    [switch]$RunOnlyCalculateVersionDistance,
    [switch]$RunOnlyCollectPackageMetadata,
    [switch]$RunOnlyExtractInternalMetrics,
    [int]$WorkersCount = 10,
    [int]$PageSizeLimit = 300,
    [int]$MaxPackagesLimit = 0
)

$ErrorActionPreference = "Stop"

function Get-PythonExe {
    if (Test-Path ".\.venv\Scripts\python.exe") {
        return ".\.venv\Scripts\python.exe"
    }
    return "python"
}

function Get-NodeExe {
    if (Get-Command node -ErrorAction SilentlyContinue) {
        return "node"
    }
    throw "Node.js no esta disponible en PATH. Instala Node.js para ejecutar JTMetrics."
}

function Ensure-RequestsInstalled {
    param([string]$PythonExe)

    & $PythonExe -m pip show requests *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[setup] Instalando requests en el entorno actual..." -ForegroundColor Yellow
        & $PythonExe -m pip install requests
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo instalar requests"
        }
    }
}

function Run-Step {
    param(
        [string]$Name,
        [string]$PythonExe,
        [string[]]$ScriptArgs
    )

    if (-not $ScriptArgs -or $ScriptArgs.Count -eq 0) {
        throw "No se recibieron argumentos para el paso: $Name"
    }

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    Write-Host "$PythonExe $($ScriptArgs -join ' ')" -ForegroundColor DarkGray
    & $PythonExe @ScriptArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo en paso: $Name"
    }
}

$pythonExe = Get-PythonExe
$startedAt = Get-Date

Write-Host "Python seleccionado: $pythonExe" -ForegroundColor Green
Ensure-RequestsInstalled -PythonExe $pythonExe

if ($RunOnlyCollectPackageMetadata) {
    Run-Step -Name "Recopilación de Metadatos de Paquetes" -PythonExe $pythonExe -ScriptArgs @("pipeline\5_package_info.py", "--workers", "$WorkersCount")
}
elseif ($RunOnlyExtractInternalMetrics) {
    $nodeExe = Get-NodeExe
    Write-Host "`n=== Extracción de Métricas Internas (JTMetrics) ===" -ForegroundColor Cyan
    Write-Host "$nodeExe `"pipeline\6_ extract_inner_metrics_jt.js`"" -ForegroundColor DarkGray
    & $nodeExe "pipeline\6_ extract_inner_metrics_jt.js"
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo en extracción de métricas internas"
    }
}
elseif ($RunOnlyCalculateVersionDistance) {
    Run-Step -Name "Cálculo de Distancia de Versiones" -PythonExe $pythonExe -ScriptArgs @("pipeline\4_version_distance.py", "--workers", "$WorkersCount")
}
elseif ($RunOnlyCalculateFanOut) {
    Run-Step -Name "Cálculo de Fan-out local" -PythonExe $pythonExe -ScriptArgs @("pipeline\3a_calc_fanout.py")
}
elseif ($RunOnlyCalculateGlobalFanIn) {
    $args3b = @("pipeline\3b_calc_fanin_global.py", "--workers", "$WorkersCount", "--page-size", "$PageSizeLimit")
    if ($MaxPackagesLimit -gt 0) { $args3b += @("--max-packages", "$MaxPackagesLimit") }
    if ($FreshStart) { $args3b += "--fresh-start" }
    Run-Step -Name "Cálculo de Fan-in Global" -PythonExe $pythonExe -ScriptArgs $args3b
}
elseif ($RunOnlyBuildDependencyGraph) {
    Run-Step -Name "Construcción del Grafo de Dependencias" -PythonExe $pythonExe -ScriptArgs @("pipeline\2_build_graph.py")
}
elseif ($RunOnlyFilterMostDownloaded) {
    Run-Step -Name "Filtrado de los Paquetes Más Descargados" -PythonExe $pythonExe -ScriptArgs @("pipeline\1_filter_popularity.py")
}
elseif ($RunOnlyExtractLargestPackages) {
    $args0 = @("pipeline\0_generate_top10k.py", "--workers", "$WorkersCount", "--page-size", "$PageSizeLimit")
    if ($MaxPackagesLimit -gt 0) { $args0 += @("--max-packages", "$MaxPackagesLimit") }
    if ($FreshStart) { $args0 += "--fresh-start" }
    Run-Step -Name "Extracción de Paquetes Más Pesados" -PythonExe $pythonExe -ScriptArgs $args0
}
else {
    if (-not $SkipExtractLargestPackages) {
        $args0 = @("pipeline\0_generate_top10k.py", "--workers", "$WorkersCount", "--page-size", "$PageSizeLimit")
        if ($MaxPackagesLimit -gt 0) { $args0 += @("--max-packages", "$MaxPackagesLimit") }
        if ($FreshStart) { $args0 += "--fresh-start" }
        Run-Step -Name "Extracción de Paquetes Más Pesados" -PythonExe $pythonExe -ScriptArgs $args0
    } else {
        Write-Host "[skip] Extracción de paquetes más pesados omitida (-SkipExtractLargestPackages)." -ForegroundColor Yellow
    }

    Run-Step -Name "Filtrado de los Paquetes Más Descargados" -PythonExe $pythonExe -ScriptArgs @("pipeline\1_filter_popularity.py")
    Run-Step -Name "Construcción del Grafo de Dependencias" -PythonExe $pythonExe -ScriptArgs @("pipeline\2_build_graph.py")
    Run-Step -Name "Cálculo de Fan-out local" -PythonExe $pythonExe -ScriptArgs @("pipeline\3a_calc_fanout.py")

    if (-not $SkipCalculateGlobalFanIn) {
        $args3b = @("pipeline\3b_calc_fanin_global.py", "--workers", "$WorkersCount", "--page-size", "$PageSizeLimit")
        if ($MaxPackagesLimit -gt 0) { $args3b += @("--max-packages", "$MaxPackagesLimit") }
        if ($FreshStart) { $args3b += "--fresh-start" }
        Run-Step -Name "Cálculo de Fan-in Global" -PythonExe $pythonExe -ScriptArgs $args3b
    } else {
        Write-Host "[skip] Cálculo de Fan-In Global omitido (-SkipCalculateGlobalFanIn)." -ForegroundColor Yellow
    }

    Run-Step -Name "Cálculo de Distancia de Versiones" -PythonExe $pythonExe -ScriptArgs @("pipeline\4_version_distance.py", "--workers", "$WorkersCount")
    Run-Step -Name "Recopilación de Metadatos de Paquetes" -PythonExe $pythonExe -ScriptArgs @("pipeline\5_package_info.py", "--workers", "$WorkersCount")

    if (-not $SkipExtractInternalMetrics) {
        $nodeExe = Get-NodeExe
        Write-Host "`n=== Extracción de Métricas Internas (JTMetrics) ===" -ForegroundColor Cyan
        Write-Host "$nodeExe `"pipeline\6_ extract_inner_metrics_jt.js`"" -ForegroundColor DarkGray
        & $nodeExe "pipeline\6_ extract_inner_metrics_jt.js"
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo en extracción de métricas internas"
        }
    } else {
        Write-Host "[skip] Extracción de métricas internas omitida (-SkipExtractInternalMetrics)." -ForegroundColor Yellow
    }
}

$elapsed = (Get-Date) - $startedAt
Write-Host "`nPipeline finalizado en $($elapsed.ToString())." -ForegroundColor Green
