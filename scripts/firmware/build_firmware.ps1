<#
.SYNOPSIS
Build firmware, optionally flashing it to an explicitly selected serial port.
.DESCRIPTION
Run in an activated ESP-IDF v6.1 PowerShell environment. Flash always builds first.
Use build_firmware_release.ps1 to generate the merged release binary.
.PARAMETER Action
Build compiles firmware. Flash compiles and writes firmware to the device.
.PARAMETER Port
Serial port required for Flash, for example COM6.
#>
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Flash')]
    [string]$Action = 'Build',
    [string]$Port
)

$ErrorActionPreference = 'Stop'
if ($Action -eq 'Flash' -and [string]::IsNullOrWhiteSpace($Port)) {
    throw 'Flash requires -Port, for example: -Action Flash -Port COM6.'
}
if ($Action -eq 'Build' -and $PSBoundParameters.ContainsKey('Port')) {
    throw '-Port is only supported with -Action Flash.'
}
if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    throw 'idf.py was not found. Activate the ESP-IDF v6.1 PowerShell environment first.'
}
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$idfArguments = @('-C', (Join-Path $repository 'firmware'))
if ($Action -eq 'Flash') { $idfArguments += @('-p', $Port) }
$idfArguments += 'build'
if ($Action -eq 'Flash') { $idfArguments += 'flash' }

Push-Location $repository
try {
    & idf.py @idfArguments
    if ($LASTEXITCODE -ne 0) { throw 'Firmware build or flash failed.' }
} finally {
    Pop-Location
}
