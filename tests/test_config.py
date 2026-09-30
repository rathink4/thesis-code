import pytest

from sbess.config import ConfigError, load_config, parse_override


def test_override_types():
    assert parse_override("battery.units=2") == {"battery": {"units": 2}}
    assert parse_override("allocation.export_shares=[0.4,0.2,0.2,0.2]") == \
        {"allocation": {"export_shares": [0.4, 0.2, 0.2, 0.2]}}


def test_cli_override_applies():
    cfg = load_config(None, ["battery.units=2", "tariff.export_mode=no_credit"])
    assert cfg["battery"]["units"] == 2 and cfg["tariff"]["export_mode"] == "no_credit"


def test_scenario_resolves_library():
    cfg = load_config("pw3_lfp")
    assert cfg["battery"]["spec"]["chemistry"] == "LFP"
    assert cfg["battery"]["spec"]["p_discharge_max_kw"] == 11.5
    assert cfg["battery"]["ageing"]["model"] == "naumann_lfp"
    assert load_config()["battery"]["ageing"]["model"] == "schmalstieg_nmc"


def test_spec_override():
    cfg = load_config(None, ["battery.spec_override={round_trip_efficiency: 0.85}"])
    assert cfg["battery"]["spec"]["round_trip_efficiency"] == 0.85


def test_typo_rejected():
    with pytest.raises(ConfigError):
        load_config(None, ["battery.unitz=2"])


def test_unknown_placement_rejected():
    with pytest.raises(ConfigError):
        load_config(None, ["battery.placement=roof"])
