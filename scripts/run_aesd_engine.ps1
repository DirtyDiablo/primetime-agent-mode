# run_aesd_engine.ps1
param(
  [string]$RepoPath = "$PSScriptRoot\.."
)
$ErrorActionPreference = "Stop"
Set-Location $RepoPath
Write-Host "Running AESD engine in $RepoPath" -ForegroundColor Cyan

$py = Join-Path $RepoPath "aesd_agent_engine.py"
if (-not (Test-Path $py)) { throw "Missing aesd_agent_engine.py in repo root." }

# Ensure data dir exists
New-Item -ItemType Directory -Force -Path "data\aesd" | Out-Null

python "$py"
