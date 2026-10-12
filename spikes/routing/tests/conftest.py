import pytest

from routewise_spike.matrix.recorded import RecordedMatrixProvider, RecordedOSRMProvider
from routewise_spike.matrix.synthetic import SyntheticMatrixProvider
from routewise_spike.scenario import (
    DU_LOCATIONS_FILE,
    RECORDED_OSRM,
    RECORDED_VALHALLA,
    load_locations,
    phase0_round,
)

# Every planner check runs on each real recorded matrix. Bengaluru is historical
# evidence only; DU North Campus (Delhi) is the confirmed delivery area.
AREAS = {
    "bengaluru-osrm-car-historical": ("bengaluru", lambda: RecordedOSRMProvider(RECORDED_OSRM)),
    "du-north-valhalla-motor_scooter": ("du_north", lambda: RecordedMatrixProvider(RECORDED_VALHALLA["motor_scooter"])),
    "du-north-valhalla-motorcycle": ("du_north", lambda: RecordedMatrixProvider(RECORDED_VALHALLA["motorcycle"])),
}


@pytest.fixture(scope="session")
def locations():
    """Bengaluru public points, used by the provider-adapter unit tests."""
    return load_locations()


@pytest.fixture(scope="session")
def du_locations():
    return load_locations(DU_LOCATIONS_FILE)


@pytest.fixture(scope="session", params=list(AREAS))
def area(request):
    return request.param


@pytest.fixture(scope="session")
def real(area):
    """Replay of a real road matrix recorded for the area's public test points."""
    return AREAS[area][1]()


@pytest.fixture
def synthetic():
    return SyntheticMatrixProvider(asymmetry=0.1)


@pytest.fixture
def make_round(area):
    area_name = AREAS[area][0]

    def _make(**kw):
        return phase0_round(area=area_name, **kw)

    return _make


PROFILE = "recorded"  # recorded providers replay the profile they were captured with
