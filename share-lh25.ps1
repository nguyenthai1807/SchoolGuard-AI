param([int]$Port = 8770)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$health = "http://127.0.0.1:$Port/api/health"
try {
    $response = Invoke-RestMethod -Uri $health -TimeoutSec 5
    if ($response.status -ne 'ok' -or $response.product -ne 'LH25') {
        throw "Cổng $Port không phải LH25."
    }
} catch {
    throw "LH25 chưa chạy ở http://127.0.0.1:$Port. Hãy chạy .\start-lh25.ps1 -Port $Port trước."
}

$tools = Join-Path $PSScriptRoot 'tools'
$cloudflared = Join-Path $tools 'cloudflared.exe'
if (-not (Test-Path -LiteralPath $cloudflared)) {
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    $download = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
    Write-Host 'Đang tải cloudflared chính chủ từ GitHub của Cloudflare...'
    Invoke-WebRequest -Uri $download -OutFile $cloudflared
}

Write-Host ''
Write-Host 'Đang tạo địa chỉ HTTPS dùng thử. Giữ cửa sổ này mở khi nhóm đang test.'
Write-Host 'Dừng chia sẻ bằng Ctrl+C. URL sẽ thay đổi ở lần chạy tiếp theo.'
Write-Host ''
& $cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$Port"
