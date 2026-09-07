"""Keep distributed campaign templates valid as the schema evolves."""
from pathlib import Path

import pytest

from fieldmatch.campaign import load_campaign


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("minimal_campaign.yaml", {"altimeter", "model"}),
        ("forecast_campaign.yaml", {"buoy", "forecast"}),
        ("extra_variables_campaign.yaml", {"sentinel3", "model"}),
    ],
)
def test_documented_campaign_is_accepted(name, expected):
    campaign = load_campaign(ROOT / "examples" / name)
    assert set(campaign.datasets) == expected
