<#
.SYNOPSIS
Build the host executable with Cargo.
.DESCRIPTION
Requires Rust and the platform's native build tools. Builds Release by default.
Use -Debug for a debug build, or build_host_release.ps1 for a Windows archive.
.PARAMETER Target
Optional Rust target triple. Defaults to CARGO_BUILD_TARGET, then the Rust host.
#>
param(
    [switch]$Debug,
    [string]$Target
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw 'Cargo was not found. Install Rust and open a new terminal.'
}
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Target) { $Target = $env:CARGO_BUILD_TARGET }
if (-not $Target) {
    $compilerInfo = & rustc -vV
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Rust compiler information.' }
    $Target = ($compilerInfo | Where-Object { $_ -match '^host: ' } | Select-Object -First 1) -replace '^host: ', ''
}
if (-not $Target) { throw 'Cannot determine the Rust target triple.' }
$buildArguments = @('build', '--manifest-path', (Join-Path $repository 'host/Cargo.toml'), '--locked', '--target', $Target)
if (-not $Debug) { $buildArguments += '--release' }
if ($Target -like '*-windows-*') { $buildArguments += @('--features', 'windows-startup') }

Push-Location $repository
try {
    & cargo @buildArguments
    if ($LASTEXITCODE -ne 0) { throw 'Host build failed.' }
} finally {
    Pop-Location
}
