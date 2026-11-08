# Windows entry point for the cross-platform font generator.
param(
    [string]$OutputPath = (Join-Path $PSScriptRoot '../../firmware/main/ui/fonts/font_maple_mono_16.c'),
    [string]$Range = '0x20-0x10FFFF'
)
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'generate_font.py') --output $OutputPath --range $Range
if ($LASTEXITCODE -ne 0) {
    throw "Font generation failed with exit code $LASTEXITCODE."
}
