#!/usr/bin/env bash
# Build the host executable in Release mode unless --debug is specified.
set -euo pipefail

repository="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
build_arguments=(build --manifest-path "$repository/host/Cargo.toml" --locked)
target="${CARGO_BUILD_TARGET:-}"
release=true
while (($#)); do
    case "$1" in
        --debug) release=false; shift ;;
        --target)
            [[ $# -ge 2 && -n "$2" ]] || { echo '--target requires a Rust target triple.' >&2; exit 2; }
            target="$2"; shift 2 ;;
        -h|--help)
            echo 'Usage: bash build_host.sh [--debug] [--target TRIPLE]'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
if "$release"; then build_arguments+=(--release); fi
command -v cargo >/dev/null || { echo 'Cargo was not found. Install Rust first.' >&2; exit 1; }
if [[ -z "$target" ]]; then
    target="$(rustc -vV | sed -n 's/^host: //p')"
fi
[[ -n "$target" ]] || { echo 'Cannot determine the Rust target triple.' >&2; exit 1; }
build_arguments+=(--target "$target")
case "$target" in
    *-windows-*) build_arguments+=(--features windows-startup) ;;
esac
cd -- "$repository"
cargo "${build_arguments[@]}"
