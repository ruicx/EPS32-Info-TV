#!/usr/bin/env bash
# Run in an activated ESP-IDF v6.1 environment. Flash always builds first.
set -euo pipefail

repository="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
action=build
port=
while (($#)); do
    case "$1" in
        --action)
            [[ $# -ge 2 ]] || { echo '--action requires build or flash.' >&2; exit 2; }
            action="$2"; shift 2 ;;
        --port)
            [[ $# -ge 2 && -n "$2" ]] || { echo '--port requires a serial port.' >&2; exit 2; }
            port="$2"; shift 2 ;;
        -h|--help)
            echo 'Usage: bash build_firmware.sh [--action build|flash] [--port /dev/ttyACM0]'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
idf_arguments=(-C "$repository/firmware")
case "$action" in
    build)
        [[ -z "$port" ]] || { echo '--port is only supported with --action flash.' >&2; exit 2; }
        idf_arguments+=(build) ;;
    flash)
        [[ -n "$port" ]] || { echo 'Flash requires --port, for example /dev/ttyACM0.' >&2; exit 2; }
        idf_arguments+=(-p "$port" build flash) ;;
    *) echo '--action must be build or flash.' >&2; exit 2 ;;
esac
command -v idf.py >/dev/null || { echo 'Activate the ESP-IDF v6.1 environment first.' >&2; exit 1; }
cd -- "$repository"
idf.py "${idf_arguments[@]}"
