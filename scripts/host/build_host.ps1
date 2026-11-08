<#
.SYNOPSIS
Build the host executable with Cargo.
.DESCRIPTION
Requires Rust and the platform's native build tools. Builds Release by default.
Use -Debug for a debug build, or build_rust_release.ps1 for a Windows archive.
.PARAMETER Target
Optional Rust target triple. When omitted, Cargo uses its configured default.
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
$buildArguments = @('build', '--manifest-path', (Join-Path $repository 'host/Cargo.toml'), '--locked', '--bins')
if (-not $Debug) { $buildArguments += '--release' }
if ($Target) { $buildArguments += @('--target', $Target) }

Push-Location $repository
try {
    & cargo @buildArguments
    if ($LASTEXITCODE -ne 0) { throw 'Host build failed.' }
} finally {
    Pop-Location
}
