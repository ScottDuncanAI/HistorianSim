"""Named, independent random substreams derived from a single master seed.

Nothing in historiansim touches the global ``np.random``. Every consumer asks the
SeedBank for a generator by name, and the name is hashed into the spawn key.

That indirection is not fussiness. It is what makes the no-fault twin dataset
comparable to the fault dataset. If draws came off one shared stream, adding a
fault would consume extra numbers and shift every subsequent draw, so the
"same run minus the fault" would silently differ everywhere -- ambient noise,
ballast tags, instrument noise, all of it. Keying by name means an unused
generator costs nothing and a new one perturbs no existing stream.
"""

from __future__ import annotations

import hashlib

import numpy as np

__all__ = ["SeedBank"]


def _name_key(name: str) -> int:
    """Map a stream name to a stable 64-bit spawn key.

    blake2b rather than ``hash()`` because Python string hashing is salted per
    process, which would make datasets irreproducible across runs.
    """
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class SeedBank:
    """Hands out reproducible, mutually independent ``np.random.Generator``s.

    >>> bank = SeedBank(42)
    >>> bank.get("ambient") is bank.get("ambient")   # cached, so state advances once
    True
    """

    def __init__(self, master_seed: int):
        self.master_seed = int(master_seed)
        self._cache: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        """Return the generator for ``name``, creating it on first request.

        Repeated calls return the *same* generator, so a caller that draws in a
        loop keeps advancing one stream rather than restarting it.
        """
        gen = self._cache.get(name)
        if gen is None:
            seq = np.random.SeedSequence(
                entropy=self.master_seed, spawn_key=(_name_key(name),)
            )
            gen = np.random.Generator(np.random.PCG64(seq))
            self._cache[name] = gen
        return gen

    def fresh(self, name: str) -> np.random.Generator:
        """Return a generator for ``name`` reset to its initial state.

        Useful when a stream must be replayed identically -- regenerating the
        same ballast tag in a fault run and a no-fault run, for instance.
        """
        self._cache.pop(name, None)
        return self.get(name)

    def __repr__(self) -> str:
        return f"SeedBank(master_seed={self.master_seed}, streams={len(self._cache)})"
