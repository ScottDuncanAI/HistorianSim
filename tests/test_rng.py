"""The determinism guarantees everything else leans on."""

import numpy as np
import pytest

from historiansim.core.rng import SeedBank


def test_same_seed_reproduces_stream():
    a = SeedBank(42).get("ambient").normal(size=100)
    b = SeedBank(42).get("ambient").normal(size=100)
    assert np.array_equal(a, b)


def test_different_seed_changes_stream():
    a = SeedBank(42).get("ambient").normal(size=100)
    b = SeedBank(43).get("ambient").normal(size=100)
    assert not np.allclose(a, b)


def test_new_stream_does_not_perturb_existing_ones():
    """The property that makes a no-fault twin comparable.

    Adding a fault adds RNG consumers. If those consumers drew from a shared
    stream they would shift every later draw, and "the same run minus the
    fault" would differ in ambient temperature and ballast tags too.
    """
    baseline = SeedBank(42).get("ambient").normal(size=100)

    bank = SeedBank(42)
    bank.get("fault_onset_jitter").normal(size=5000)  # a consumer added later
    assert np.array_equal(bank.get("ambient").normal(size=100), baseline)


def test_distinct_names_are_independent():
    bank = SeedBank(42)
    feed = bank.get("feed_flow").normal(size=2000)
    steam = bank.get("steam_header").normal(size=2000)
    assert abs(np.corrcoef(feed, steam)[0, 1]) < 0.1


def test_get_is_cached_so_the_stream_advances():
    bank = SeedBank(42)
    first = bank.get("x").normal(size=10)
    second = bank.get("x").normal(size=10)
    assert not np.allclose(first, second), "get() must not restart the stream"


def test_fresh_restarts_the_stream():
    bank = SeedBank(42)
    first = bank.get("x").normal(size=10)
    bank.get("x").normal(size=10)
    assert np.array_equal(bank.fresh("x").normal(size=10), first)


@pytest.mark.parametrize("name", ["ambient", "feed", "TI-101", "unit_2/LIC-205.PV"])
def test_stream_names_are_process_independent(name):
    """Python's str hash is salted per process; ours must not be."""
    assert np.array_equal(
        SeedBank(7).get(name).normal(size=20),
        SeedBank(7).get(name).normal(size=20),
    )
