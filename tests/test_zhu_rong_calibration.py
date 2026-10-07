from __future__ import annotations

import math

from sanmou_sim.models import General
from sanmou_sim.skills import _calibrated_value


HEAL_EFFECT = {
    "calibrated_formula": {
        "stat": "武力",
        "base": 0.25,
        "coefficient": 0.00628895,
        "exponent": 0.7751312,
    }
}
STEAL_EFFECT = {
    "calibrated_formula": {
        "stat": "武力",
        "base": 20.0,
        "coefficient": 0.00538112,
        "exponent": 0.7989526,
    }
}


def general(force: int) -> General:
    return General("祝融夫人", 10000, force, 100, 300, 100, [])


def test_southern_blade_calibrated_values_have_text_baseline() -> None:
    # General.stat() clamps combat attributes to at least 1 point.
    assert math.isclose(
        _calibrated_value(general(1), HEAL_EFFECT, "heal_rate", 0.25),
        0.25 * (1 + 0.00628895),
    )
    assert math.isclose(
        _calibrated_value(general(1), STEAL_EFFECT, "force_stolen", 20),
        20.0 * (1 + 0.00538112),
    )


def test_southern_blade_calibrated_values_increase_with_force() -> None:
    low = general(200)
    high = general(500)
    assert _calibrated_value(high, HEAL_EFFECT, "heal_rate", 0.25) > _calibrated_value(low, HEAL_EFFECT, "heal_rate", 0.25)
    assert _calibrated_value(high, STEAL_EFFECT, "force_stolen", 20) > _calibrated_value(low, STEAL_EFFECT, "force_stolen", 20)
