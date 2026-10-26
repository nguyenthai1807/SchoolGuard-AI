param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('LH25_PAYOS_CLIENT_ID','LH25_PAYOS_API_KEY','LH25_PAYOS_CHECKSUM_KEY')]
    [string]$Key
)
$ErrorActionPreference = 'Stop'
$projectFolder = Split-Path -Parent $PSScriptRoot
$configFile = Join-Path $projectFolder '.env'
$secretValue = (Get-Clipboard -Raw).Trim()
if ($secretValue -notmatch '^[A-Za-z0-9_-]{16,256}$') {
    throw 'Clipboard does not contain a valid copied payOS key. Configuration was not changed.'
}
$oldLines = if (Test-Path -LiteralPath $configFile) { [IO.File]::ReadAllLines($configFile) } else { @() }
$newLines = [Collections.Generic.List[string]]::new()
$foundKey = $false
foreach ($line in $oldLines) {
    if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
        if (-not $foundKey) { $newLines.Add($Key + '=' + $secretValue); $foundKey=$true }
    } else { $newLines.Add($line) }
}
if (-not $foundKey) { $newLines.Add($Key + '=' + $secretValue) }
if (Test-Path -LiteralPath $configFile) {
    $backupFolder=Join-Path $projectFolder 'runtime/backups'
    [IO.Directory]::CreateDirectory($backupFolder) | Out-Null
    Copy-Item -LiteralPath $configFile -Destination (Join-Path $backupFolder ('env-payos-' + [guid]::NewGuid().ToString('N') + '.txt'))
}
$stagingFile=Join-Path $projectFolder ('.env-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllLines($stagingFile,$newLines,[Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $stagingFile -Destination $configFile -Force
    if ((Get-Clipboard -Raw).Trim() -ceq $secretValue) { Set-Clipboard -Value '' }
    Write-Output ($Key + ': saved; value hidden')
} finally {
    $secretValue=$null
    $newLines.Clear()
    if(Test-Path -LiteralPath $stagingFile){Remove-Item -LiteralPath $stagingFile}
}
