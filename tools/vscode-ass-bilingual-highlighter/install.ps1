$ErrorActionPreference = "Stop"

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content -Raw -LiteralPath (Join-Path $source "package.json") | ConvertFrom-Json
$extensionName = "$($manifest.publisher).$($manifest.name)-$($manifest.version)"
$targetRoot = Join-Path $env:USERPROFILE ".vscode\extensions"
$target = Join-Path $targetRoot $extensionName

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
Write-Host "Installed $($manifest.displayName) to $target"
Write-Host "Reload VS Code, then reopen any .ass or .ssa file."
