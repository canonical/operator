import sys
from pathlib import Path


def setup_tests():
    runtime_path = Path(__file__).parent.parent / "scenario" / "runtime"
    sys.path.append(str(runtime_path))  # allow 'import memo'

    from scenario import Runtime

    Runtime.install(force=False)  # ensure Runtime is installed
