import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def pipeline_results():
    """Generate the synthetic data, run ETL and all tests once for the session."""
    from src import etl, generate_data
    from src.pipeline import analyse

    generate_data.main()
    quality = etl.run().frames()
    return analyse(quality=quality)
