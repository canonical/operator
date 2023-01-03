#! /bin/python3
import sys
from pathlib import Path


def install_runtime():
    runtime_path = Path(__file__).parent.parent.parent.parent
    sys.path.append(str(runtime_path))  # allow 'import memo'

    from scenario import Runtime

    Runtime.install(force=False)  # ensure Runtime is installed


if __name__ == "__main__":
    install_runtime()
