"""Make `custom_stack` importable when tests are run with
`python -m unittest discover platform-evaluation/custom_stack/tests`."""
import sys
from pathlib import Path

PLATFORM_EVAL = Path(__file__).resolve().parents[2]
if str(PLATFORM_EVAL) not in sys.path:
    sys.path.insert(0, str(PLATFORM_EVAL))

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
BENCHMARK_FIXTURES = PLATFORM_EVAL / "benchmark" / "fixtures"


def ensure_fixtures() -> Path:
    if not (FIXTURES / "ipeds_institution.parquet").exists():
        sys.path.insert(0, str(FIXTURES.parent))
        import build_fixtures  # noqa: E402

        build_fixtures.build(FIXTURES)
    return FIXTURES
