import pytest

from routewise_spike.matrix.recorded import RecordedOSRMProvider
from routewise_spike.matrix.synthetic import SyntheticMatrixProvider
from routewise_spike.scenario import RECORDED_OSRM, load_locations, phase0_round


@pytest.fixture(scope="session")
def locations():
    return load_locations()


@pytest.fixture(scope="session")
def real():
    """Replay of a real OSRM road matrix captured for the public test points."""
    return RecordedOSRMProvider(RECORDED_OSRM)


@pytest.fixture
def synthetic():
    return SyntheticMatrixProvider(asymmetry=0.1)


@pytest.fixture
def make_round(locations):
    def _make(**kw):
        return phase0_round(locations, **kw)

    return _make


PROFILE = "car_proxy"
