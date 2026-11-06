"""Generate or verify the checked-in Python and Nanopb device bindings.

Notes
-----
Run with ``uv run --project host python scripts/generate_protocol.py``.
The generator never downloads or modifies third-party runtime sources.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """Generate bindings, or fail if checked-in bindings differ.

    Raises
    ------
    RuntimeError
        If Nanopb is unavailable or generated files are outdated.
    subprocess.CalledProcessError
        If either compiler fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.find_spec("nanopb")
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError("Install the host development dependencies first")
    generator = Path(next(iter(spec.submodule_search_locations))) / "generator" / "nanopb_generator.py"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{root / 'protocol'}", f"--python_out={output}", f"--pyi_out={output}", str(root / "protocol/device.proto")], check=True)
        subprocess.run([sys.executable, str(generator), f"-I{root / 'protocol'}", f"-D{output}", str(root / "protocol/device.proto")], check=True)
        targets = {
            "device_pb2.py": root / "host/src/info_tv_service/device/generated",
            "device_pb2.pyi": root / "host/src/info_tv_service/device/generated",
            "device.pb.c": root / "firmware/main/protocol/generated",
            "device.pb.h": root / "firmware/main/protocol/generated",
        }
        for filename, destination in targets.items():
            source = output / filename
            target = destination / filename
            if args.check:
                if not target.exists() or target.read_bytes() != source.read_bytes():
                    raise RuntimeError(f"Outdated generated file: {target}")
            else:
                destination.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
