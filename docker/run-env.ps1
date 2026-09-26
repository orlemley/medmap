# Start MedMap with Docker (Windows PowerShell). Run from anywhere:
#
#   ./docker/run-env.ps1          build and start the demo on http://localhost:8000
#   ./docker/run-env.ps1 -Dev     also start the hot-reload React dev server on :5173
#   ./docker/run-env.ps1 -Down    stop and remove the containers
#
# Needs Docker Desktop running. Press Ctrl+C to stop.
param(
    [switch]$Dev,
    [switch]$Down
)

$compose = Join-Path $PSScriptRoot "docker-compose.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker isn't installed. Get Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

if ($Down) {
    docker compose -f $compose --profile dev down
    exit $LASTEXITCODE
}

$composeArgs = @("-f", $compose)
if ($Dev) { $composeArgs += @("--profile", "dev") }

Write-Host "Starting MedMap: http://localhost:8000" -NoNewline
if ($Dev) { Write-Host " (React dev server: http://localhost:5173)" } else { Write-Host "" }
docker compose @composeArgs up --build
