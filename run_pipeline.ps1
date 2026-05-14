param(
    [switch]$FreshStart,
    [switch]$SkipTop10k,
    [switch]$SkipFanin,
    [switch]$OnlyTop10k,
    [switch]$OnlyFilter,
    [switch]$OnlyGraph,
    [switch]$OnlyFanout,
    [switch]$OnlyFanin,
    [int]$Workers = 10,
    [int]$PageSize = 300,
    [int]$MaxPackages = 0
)

$ErrorActionPreference = "Stop"

function Get-PythonExe {
    if (Test-Path ".\.venv\Scripts\python.exe") {
        return ".\.venv\Scripts\python.exe"
    }
    return "python"
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

    Write-Host "\n=== $Name ===" -ForegroundColor Cyan
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

if ($OnlyFanout) {
    Run-Step -Name "Paso 3a: Calcular fan-out" -PythonExe $pythonExe -ScriptArgs @("pipeline\3a_calc_fanout.py")
}
elseif ($OnlyFanin) {
    $args3b = @("pipeline\3b_calc_fanin_global.py", "--workers", "$Workers", "--page-size", "$PageSize")
    if ($MaxPackages -gt 0) { $args3b += @("--max-packages", "$MaxPackages") }
    if ($FreshStart) { $args3b += "--fresh-start" }
    Run-Step -Name "Paso 3b: Calcular fan-in global" -PythonExe $pythonExe -ScriptArgs $args3b
}
elseif ($OnlyGraph) {
    Run-Step -Name "Paso 2: Construir grafo final" -PythonExe $pythonExe -ScriptArgs @("pipeline\2_build_graph.py")
}
elseif ($OnlyFilter) {
    Run-Step -Name "Paso 1: Filtrar top 5000 por descargas" -PythonExe $pythonExe -ScriptArgs @("pipeline\1_filter_popularity.py")
}
elseif ($OnlyTop10k) {
    $args0 = @("pipeline\0_generate_top10k.py", "--workers", "$Workers", "--page-size", "$PageSize")
    if ($MaxPackages -gt 0) { $args0 += @("--max-packages", "$MaxPackages") }
    if ($FreshStart) { $args0 += "--fresh-start" }
    Run-Step -Name "Paso 0: Generar top 10k pesados" -PythonExe $pythonExe -ScriptArgs $args0
}
else {
    if (-not $SkipTop10k) {
        $args0 = @("pipeline\0_generate_top10k.py", "--workers", "$Workers", "--page-size", "$PageSize")
        if ($MaxPackages -gt 0) { $args0 += @("--max-packages", "$MaxPackages") }
        if ($FreshStart) { $args0 += "--fresh-start" }
        Run-Step -Name "Paso 0: Generar top 10k pesados" -PythonExe $pythonExe -ScriptArgs $args0
    }

    Run-Step -Name "Paso 1: Filtrar top 5000 por descargas" -PythonExe $pythonExe -ScriptArgs @("pipeline\1_filter_popularity.py")
    Run-Step -Name "Paso 2: Construir grafo final" -PythonExe $pythonExe -ScriptArgs @("pipeline\2_build_graph.py")
    Run-Step -Name "Paso 3a: Calcular fan-out" -PythonExe $pythonExe -ScriptArgs @("pipeline\3a_calc_fanout.py")

    if (-not $SkipFanin) {
        $args3b = @("pipeline\3b_calc_fanin_global.py", "--workers", "$Workers", "--page-size", "$PageSize")
        if ($MaxPackages -gt 0) { $args3b += @("--max-packages", "$MaxPackages") }
        if ($FreshStart) { $args3b += "--fresh-start" }
        Run-Step -Name "Paso 3b: Calcular fan-in global" -PythonExe $pythonExe -ScriptArgs $args3b
    } else {
        Write-Host "[skip] Paso 3b omitido (-SkipFanin)." -ForegroundColor Yellow
    }
}

$elapsed = (Get-Date) - $startedAt
Write-Host "\nPipeline finalizado en $($elapsed.ToString())." -ForegroundColor Green
