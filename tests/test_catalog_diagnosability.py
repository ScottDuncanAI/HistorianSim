"""Can every root cause in every plant's catalog be diagnosed from the data?

The sweep itself lives in :mod:`historiansim.validation.catalog` so that
``historiansim check-plant`` runs exactly the same thing. Here it runs once per
registered plant: each cause injected on its own against identical weather,
measured through the full instrument and transport-lag chain. Marked slow --
it runs a simulation per cause.
"""

import pytest

from historiansim.plants import all_plants
from historiansim.validation.catalog import (
    dangling_tags,
    flat_violations,
    indistinguishable,
    sweep_catalog,
    undiagnosable,
)

PLANTS = all_plants()
IDS = [p.name for p in PLANTS]


@pytest.fixture(scope="module", params=PLANTS, ids=IDS)
def swept(request):
    plant = request.param
    return plant, sweep_catalog(plant)


@pytest.mark.slow
def test_every_cause_has_evidence_that_actually_moves(swept):
    """Every cause must leave at least one directional trace in the data."""
    plant, sweep = swept
    bad = undiagnosable(sweep)
    assert not bad, {
        cid: {tag: round(e.peak, 4) for tag, e in sweep[cid].items()} for cid in bad
    }


@pytest.mark.slow
def test_evidence_expected_flat_really_is_flat(swept):
    """A 'flat' expectation is what rules a competitor out."""
    _, sweep = swept
    assert not flat_violations(sweep)


@pytest.mark.slow
def test_candidates_within_a_symptom_are_distinguishable(swept):
    """The premise of the dataset: same symptom, separable causes."""
    plant, sweep = swept
    assert not indistinguishable(plant, sweep)


@pytest.mark.parametrize("plant", PLANTS, ids=IDS)
def test_every_catalog_tag_exists_in_the_dataset(plant):
    """Cheap guard against the mismatch that broke four causes silently."""
    assert not dangling_tags(plant)
