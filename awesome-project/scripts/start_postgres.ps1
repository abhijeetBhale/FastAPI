<#
.SYNOPSIS
    Ensures the PostgreSQL server is running, and reports how to stop it.

.DESCRIPTION
    Safe to run as a normal user. If the service is already running this just
    confirms it. Starting or stopping a Windows service requires an elevated
    (Administrator) shell, so if the server is down and this script is not
    elevated it prints the exact command to run instead of failing cryptically.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_postgres.ps1
#>

$ErrorActionPreference = "Stop"

$service = "postgresql-x64-17"
$bin     = "C:\Program Files\PostgreSQL\17\bin"

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-PgAccepting {
    if (-not (Test-Path (Join-Path $bin "pg_isready.exe"))) { return $null }
    & (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p 5432 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$svc = Get-Service -Name $service -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "Service '$service' not found." -ForegroundColor Red
    Write-Host "Install PostgreSQL first:"
    Write-Host "  winget install --id PostgreSQL.PostgreSQL.17 --exact"
    exit 1
}

Write-Host ("Service     : {0}" -f $service)
Write-Host ("Status      : {0}" -f $svc.Status)
Write-Host ("Startup type: {0}" -f $svc.StartType)

if ($svc.Status -eq "Running" -and (Test-PgAccepting)) {
    Write-Host "`nPostgreSQL is up and accepting connections." -ForegroundColor Green
    Write-Host "  host 127.0.0.1   port 5432"
    Write-Host "  user postgres    password postgres"
    Write-Host ""
    Write-Host "Next:"
    Write-Host "  .venv\Scripts\python.exe scripts\setup_postgres.py    # first run only"
    Write-Host "  .venv\Scripts\python.exe -m uvicorn main:app --reload"
    exit 0
}

# ---- Server is down -------------------------------------------------- #
Write-Host "`nPostgreSQL is not running." -ForegroundColor Yellow

if (-not (Test-Elevated)) {
    Write-Host "This shell is not elevated, so the service cannot be controlled." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Right-click PowerShell -> 'Run as administrator', then:"
    Write-Host ""
    Write-Host "  Start-Service $service"
    Write-Host ""
    Write-Host "Or start it from the Services console:"
    Write-Host "  services.msc  ->  find '$service'  ->  Start"
    exit 2
}

Write-Host "Starting..."
Start-Service -Name $service
$svc = Get-Service -Name $service
$svc.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))

if ((Get-Service -Name $service).Status -eq "Running") {
    Start-Sleep -Seconds 2
    if (Test-PgAccepting) {
        Write-Host "`nPostgreSQL started and is accepting connections." -ForegroundColor Green
        exit 0
    }
    Write-Host "`nService is Running but not accepting connections yet." -ForegroundColor Yellow
    Write-Host "Check the log: C:\Program Files\PostgreSQL\17\data\log\"
    exit 3
}

Write-Host "Failed to start." -ForegroundColor Red
exit 1