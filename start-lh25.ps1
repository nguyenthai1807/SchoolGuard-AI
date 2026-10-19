param([int]$Port = 8766, [string]$Dataset = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Dataset) { $env:SCHOOLGUARD_DATA = $Dataset }
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    throw 'Chạy python -m venv .venv và pip install -r requirements-dev.txt trước.'
}
Write-Host "LH25: http://127.0.0.1:$Port"
Write-Host 'Tài khoản: admin. Mật khẩu: trong .env; nếu chưa đặt, xem runtime/admin-password.txt sau lần chạy đầu.'
& ./.venv/Scripts/python.exe -m uvicorn schoolguard.app:create_app --factory --host 127.0.0.1 --port $Port --workers 1
