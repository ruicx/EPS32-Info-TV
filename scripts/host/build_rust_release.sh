#!/usr/bin/env bash
# Package Linux host executables, configuration, and README in a tar.gz archive.
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd -- "$script_directory/../.." && pwd)"
target=
while (($#)); do
    case "$1" in
        --target)
            [[ $# -ge 2 && -n "$2" ]] || { echo '--target requires a Rust target triple.' >&2; exit 2; }
            target="$2"; shift 2 ;;
        -h|--help)
            echo 'Usage: bash build_rust_release.sh [--target LINUX_TRIPLE]'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
for tool in cargo rustc python3 tar sha256sum; do
    command -v "$tool" >/dev/null || { echo "Required tool not found: $tool" >&2; exit 1; }
done
if [[ -z "$target" ]]; then
    target="$(rustc -vV | sed -n 's/^host: //p')"
fi
case "$target" in
    *-unknown-linux-gnu|*-unknown-linux-musl|*-unknown-linux-gnueabihf|*-unknown-linux-musleabihf) ;;
    *) echo 'This packaging script supports Linux targets only.' >&2; exit 2 ;;
esac
cd -- "$repository"
bash "$script_directory/build_host.sh" --target "$target"
metadata="$(cargo metadata --manifest-path "$repository/host/Cargo.toml" --locked --no-deps --format-version 1)"
package_info="$(printf '%s' "$metadata" | python3 -c '
import json
import sys
metadata = json.load(sys.stdin)
package = next(package for package in metadata["packages"] if package["name"] == "info-tv")
print(package["version"])
print(metadata["target_directory"])
')"
package_info="${package_info//$'\r'/}"
version="${package_info%%$'\n'*}"
target_directory="${package_info#*$'\n'}"
output="$repository/build/rust-host-dist"
mkdir -p -- "$output"
stage="$(mktemp -d "$output/staging-XXXXXXXX")"
binary_directory="$target_directory/$target/release"
cp -- "$binary_directory/info-tv" "$binary_directory/info-tv-hook" "$stage/"
cp -- "$repository/host/info-tv.example.yaml" "$stage/info-tv.yaml"
cp -- "$repository/host/README.md" "$stage/README.md"
archive="$output/info-tv-$version-$target.tar.gz"
tar -czf "$archive" -C "$stage" info-tv info-tv-hook info-tv.yaml README.md
sha256sum -- "$archive"
printf 'Archive: %s\n' "$archive"
