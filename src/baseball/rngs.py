"""Per-plate-appearance random streams.

A single shared generator makes determinism brittle. Any change to the
*number* of draws shifts every downstream result, so in v0.1 the
calibration numbers moved whenever a probability was touched, even when the
change should have been behaviorally neutral. Deriving an independent
stream per plate appearance means changing the whiff formula perturbs only
the at-bats it actually touches.

Two deliberate departures from the v0.3 sketch, which was
`hash((game_seed, inning, half, batter_index))`:

1. **Not `hash()`.** Python randomizes string hashing per process, so that
   formula gives a different game every run for the same seed -- exactly
   the property it was added to provide. SHA-256 over a formatted key is
   stable across processes and machines.

2. **A plate-appearance index is included.** `batter_index` alone collides
   when a team bats around: the same batter in the same half-inning would
   get a byte-identical stream, and therefore a byte-identical outcome.
"""

from __future__ import annotations

import hashlib
import random


def derive(
    game_seed: int,
    inning: int,
    half: str,
    pa_index: int,
    batter_index: int,
    tag: str = "pa",
) -> random.Random:
    """An independent generator for one plate appearance.

    `tag` separates streams that belong to the same slot but different
    decisions, so a steal attempt doesn't consume draws the at-bat needs.
    """
    key = f"{game_seed}:{inning}:{half}:{pa_index}:{batter_index}:{tag}"
    return random.Random(hashlib.sha256(key.encode()).digest())
