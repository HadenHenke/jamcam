$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = python -c "import sys; sys.path.insert(0,'$dir'); import config; print(config.PORT)"

# Install ngrok if missing
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "Installing ngrok..." -ForegroundColor Yellow
    winget install ngrok.ngrok --silent
    Write-Host "Done. Please re-run this script." -ForegroundColor Cyan
    pause
    exit
}

# Authenticate ngrok if needed
$config = "$env:USERPROFILE\.config\ngrok\ngrok.yml"
$alt    = "$env:LOCALAPPDATA\ngrok\ngrok.yml"
$hasToken = ((Test-Path $config) -and (Select-String -Path $config -Pattern "authtoken" -Quiet)) -or
            ((Test-Path $alt)    -and (Select-String -Path $alt    -Pattern "authtoken" -Quiet))

if (-not $hasToken) {
    Write-Host ""
    Write-Host "One-time setup: create a free account at https://dashboard.ngrok.com/signup" -ForegroundColor Yellow
    Write-Host "Copy your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken" -ForegroundColor Yellow
    Write-Host ""
    $token = Read-Host "Paste authtoken"
    ngrok config add-authtoken $token
}

# Start server
Write-Host "Starting server..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit -Command cd '$dir'; python app.py"
Start-Sleep -Seconds 2

# Start ngrok
Write-Host "Starting tunnel..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit -Command ngrok http $port"
Start-Sleep -Seconds 3

# Print URL
try {
    $tunnels = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels"
    $url = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" }).public_url
    Write-Host ""
    Write-Host "================================" -ForegroundColor Cyan
    Write-Host "  Open on your phone:" -ForegroundColor Cyan
    Write-Host "  $url" -ForegroundColor White
    Write-Host "================================" -ForegroundColor Cyan
} catch {
    Write-Host "Check the ngrok window for your https:// URL." -ForegroundColor Cyan
}

pause
