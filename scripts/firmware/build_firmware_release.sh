#!/usr/bin/env bash
# Build and package the merged ESP32-S3 firmware release binary.
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd -- "$script_directory/../.." && pwd)"

while (($#)); do
    case "$1" in
        -h|--help)
            echo 'Usage: bash build_firmware_release.sh'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

command -v idf.py >/dev/null || { echo 'Activate the ESP-IDF v6.1 environment first.' >&2; exit 1; }

version="$(grep -m1 '^version = ' "$repository/host/Cargo.toml" | sed 's/^version = "\(.*\)"$/\1/')"
if [[ -z "$version" ]]; then
    echo 'Cannot read package version from host/Cargo.toml.' >&2
    exit 1
fi

bash "$script_directory/build_firmware.sh" --action build

binary_name="info_tv-firmware-$version-esp32s3.bin"
cd -- "$repository"
idf.py -C firmware merge-bin -o "$binary_name"

source_binary="$repository/firmware/build/$binary_name"
if [[ ! -f "$source_binary" ]]; then
    echo "Expected merged binary not found at $source_binary." >&2
    exit 1
fi

output="$repository/build/firmware-dist"
mkdir -p -- "$output"
destination_binary="$output/$binary_name"
cp -- "$source_binary" "$destination_binary"

if command -v sha256sum >/dev/null; then
    sha256sum -- "$destination_binary"
fi
printf 'Archive: %s\n' "$destination_binary"
