<#
.SYNOPSIS
Build and package the merged ESP32-S3 firmware release binary.
.DESCRIPTION
Run in an activated ESP-IDF v6.1 PowerShell environment.
Builds the firmware, merges the bootloader, partition table, and application
into a single 0x0 flashable binary, and writes it to build/firmware-dist.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw 'idf.py was not found. Activate the ESP-IDF v6.1 PowerShell environment first.'
}

$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$manifest = Join-Path $repository 'host/Cargo.toml'
$manifestContent = Get-Content -LiteralPath $manifest -Raw
if ($manifestContent -match '(?m)^version\s*=\s*"([^"]+)"') {
    $version = $Matches[1]
} else {
    throw 'Cannot read package version from host/Cargo.toml.'
}

$firmwareDirectory = Join-Path $repository 'firmware'
$binaryName = "info_tv-firmware-$version-esp32s3.bin"
$output = Join-Path $repository 'build/firmware-dist'

Push-Location $repository
try {
    & (Join-Path $PSScriptRoot 'build_firmware.ps1') -Action Build

    & idf.py -C $firmwareDirectory merge-bin -o $binaryName
    if ($LASTEXITCODE -ne 0) { throw 'Firmware merge-bin failed.' }

    $sourceBinary = Join-Path $firmwareDirectory "build/$binaryName"
    if (-not (Test-Path -LiteralPath $sourceBinary)) {
        throw "Expected merged binary not found at $sourceBinary."
    }

    New-Item -ItemType Directory -Force $output | Out-Null
    $destinationBinary = Join-Path $output $binaryName
    Copy-Item -LiteralPath $sourceBinary -Destination $destinationBinary -Force

    Get-FileHash -LiteralPath $destinationBinary -Algorithm SHA256 | Format-List
    Write-Output "Archive: $destinationBinary"
} finally {
    Pop-Location
}
