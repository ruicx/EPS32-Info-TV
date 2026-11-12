<#
.SYNOPSIS
Build a Windows host archive with a statically linked MSVC runtime.
.DESCRIPTION
Produces info-tv.exe, the native info-tv-startup.exe launcher, configuration, and a
quick-start guide. Does not register startup, open serial ports, or publish a release.
#>
[CmdletBinding()]
param(
    [string]$Target
)

$ErrorActionPreference = 'Stop'
if (-not $Target) { $Target = $env:CARGO_BUILD_TARGET }
if (-not $Target) {
    $compilerInfo = & rustc -vV
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Rust compiler information.' }
    $Target = ($compilerInfo | Where-Object { $_ -match '^host: ' } | Select-Object -First 1) -replace '^host: ', ''
}
if ($Target -notin @('x86_64-pc-windows-msvc', 'aarch64-pc-windows-msvc')) {
    throw 'This packaging script supports Windows MSVC targets only.'
}
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$manifest = Join-Path $repository 'host/Cargo.toml'
$previousFlags = $env:RUSTFLAGS
try {
    $env:RUSTFLAGS = (($previousFlags, '-C target-feature=+crt-static') | Where-Object { $_ }) -join ' '
    & (Join-Path $PSScriptRoot 'build_host.ps1') -Target $Target
    $metadataText = & cargo metadata --manifest-path $manifest --locked --no-deps --format-version 1
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Rust package metadata.' }
    $metadata = $metadataText | ConvertFrom-Json
    $version = ($metadata.packages | Where-Object { $_.name -eq 'info-tv' }).version
    $output = Join-Path $repository 'build/host-dist'
    $stage = Join-Path $output ('staging-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $stage | Out-Null
    $binaryDirectory = Join-Path $metadata.target_directory "$Target/release"
    Copy-Item -LiteralPath (Join-Path $binaryDirectory 'info-tv.exe') -Destination $stage
    Copy-Item -LiteralPath (Join-Path $binaryDirectory 'info-tv-startup.exe') -Destination $stage
    Copy-Item -LiteralPath (Join-Path $repository 'host/info-tv.example.yaml') -Destination (Join-Path $stage 'info-tv.yaml')
    Copy-Item -LiteralPath (Join-Path $repository 'host/README.md') -Destination $stage
    $archive = Join-Path $output "info-tv-$version-$Target.zip"
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -Force
    Get-FileHash -LiteralPath $archive -Algorithm SHA256 | Format-List
    Write-Output "Archive: $archive"
} finally {
    $env:RUSTFLAGS = $previousFlags
}
