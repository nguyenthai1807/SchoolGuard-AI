param([string]$PublicBaseUrl = '')
$ErrorActionPreference = 'Stop'

# Run interactively on the owner's computer. Never echo credentials or put them
# in command-line arguments. Cloud production uses Secret Manager instead.
function Read-SecretValue([string]$Label) {
    $secureValue = Read-Host $Label -AsSecureString
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Contains("`r") -or $value.Contains("`n")) {
            throw 'Gia tri khong duoc rong hoac chua ky tu xuong dong.'
        }
        return $value
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
        $secureValue.Dispose()
    }
}

if ($PublicBaseUrl) {
    $siteUri = [uri]$PublicBaseUrl
    if ($siteUri.Scheme -ne 'https' -or $siteUri.HostNameType -ne 'Dns' -or
        $siteUri.Host.EndsWith('.trycloudflare.com') -or $siteUri.AbsolutePath -ne '/' -or
        $siteUri.Query -or $siteUri.Fragment -or $siteUri.UserInfo -or -not $siteUri.IsDefaultPort) {
        throw 'Can ten mien HTTPS co dinh, khong co duong dan hoac tunnel tam.'
    }
}

Write-Host 'Nhap khoa cua KENH THANH TOAN payOS. Du lieu bi an khi go.'
Write-Host 'Script chi luu cau hinh cuc bo; chua bat thanh toan va khong tao giao dich.'
$changes = [ordered]@{}
$changes['LH25_PAYOS_CLIENT_ID'] = Read-SecretValue 'payOS Client ID'
$changes['LH25_PAYOS_API_KEY'] = Read-SecretValue 'payOS API key'
$changes['LH25_PAYOS_CHECKSUM_KEY'] = Read-SecretValue 'payOS Checksum key'
if ($PublicBaseUrl) { $changes['LH25_PUBLIC_BASE_URL'] = $PublicBaseUrl.TrimEnd('/') }

$configFile = Join-Path $PSScriptRoot '.env'
$oldLines = if (Test-Path -LiteralPath $configFile) { [IO.File]::ReadAllLines($configFile) } else { @() }
$newLines = [Collections.Generic.List[string]]::new()
$replacedKeys = [Collections.Generic.HashSet[string]]::new()
foreach ($line in $oldLines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
        $configKey = $Matches[1]
        if ($changes.Contains($configKey)) {
            if ($replacedKeys.Add($configKey)) { $newLines.Add($configKey + '=' + $changes[$configKey]) }
            continue
        }
    }
    $newLines.Add($line)
}
foreach ($configKey in $changes.Keys) {
    if ($replacedKeys.Add($configKey)) { $newLines.Add($configKey + '=' + $changes[$configKey]) }
}
if (Test-Path -LiteralPath $configFile) {
    $backupFolder = Join-Path $PSScriptRoot 'runtime/backups'
    [IO.Directory]::CreateDirectory($backupFolder) | Out-Null
    $backupFile = Join-Path $backupFolder ('env-before-commerce-' + [guid]::NewGuid().ToString('N') + '.txt')
    Copy-Item -LiteralPath $configFile -Destination $backupFile
}
$stagingFile = Join-Path $PSScriptRoot ('.env-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllLines($stagingFile, $newLines, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $stagingFile -Destination $configFile -Force
} finally {
    if (Test-Path -LiteralPath $stagingFile) { Remove-Item -LiteralPath $stagingFile }
    $changes.Clear()
}
Write-Host 'Da luu khoa payOS vao .env. Cau hinh cu da duoc giu; chua bat thu tien.'
Write-Host 'Tiep theo: cau hinh email, ten mien HTTPS va webhook truoc khi bat thanh toan.'
