"""Config validation should catch the mistakes that are painful to debug later."""

import pytest
from pydantic import ValidationError

from historiansim.config import LoopConfig, ScenarioConfig, TimeConfig, config_hash


def test_scan_and_sub_step_counts():
    t = TimeConfig(days=90, dt_scan=10.0, dt_sim=1.0)
    assert t.n_steps == 777_600
    assert t.n_sub == 10
    assert t.duration_s == 90 * 86400


def test_scan_must_be_multiple_of_integration_step():
    with pytest.raises(ValidationError, match="integer multiple"):
        TimeConfig(dt_scan=10.0, dt_sim=3.0)


def test_integration_step_cannot_exceed_scan():
    with pytest.raises(ValidationError):
        TimeConfig(dt_scan=1.0, dt_sim=10.0)


def test_unknown_keys_are_rejected():
    """A mis-spelled gain silently reverting to a default is a lost afternoon."""
    with pytest.raises(ValidationError):
        ScenarioConfig(name="a", unit="b", kcc=1.0)


def test_output_limits_must_be_ordered():
    with pytest.raises(ValidationError, match="out_max"):
        LoopConfig(name="X", pv_source="T", mv_tag="V", kc=1, sp=1, out_min=0.5, out_max=0.2)


def test_manual_output_must_be_within_limits():
    with pytest.raises(ValidationError, match="man_output"):
        LoopConfig(name="X", pv_source="T", mv_tag="V", kc=1, sp=1, man_output=1.5)


def test_duplicate_loop_names_rejected():
    loop = dict(pv_source="T", mv_tag="V", kc=1.0, sp=50.0)
    with pytest.raises(ValidationError, match="duplicate loop names"):
        ScenarioConfig(
            name="a", unit="b",
            loops=[LoopConfig(name="TIC-101", **loop), LoopConfig(name="TIC-101", **loop)],
        )


def _demo_config() -> ScenarioConfig:
    return ScenarioConfig(
        name="exchanger-fouling",
        unit="heated_stirred_tank",
        seed=42,
        params={"area": 3.14},
        loops=[LoopConfig(name="TIC-101", pv_source="T", mv_tag="TV-101", kc=0.08, ti=240.0, sp=75.0)],
    )


def test_config_hash_is_stable_and_sensitive():
    cfg = _demo_config()
    assert config_hash(cfg) == config_hash(cfg.model_copy(deep=True))

    changed = cfg.model_copy(deep=True)
    changed.seed = 43
    assert config_hash(cfg) != config_hash(changed)


def test_loop_lookup():
    cfg = _demo_config()
    assert cfg.loop("TIC-101").kc == 0.08
    with pytest.raises(KeyError):
        cfg.loop("LIC-101")
