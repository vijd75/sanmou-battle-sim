from __future__ import annotations

import math

from sanmou_sim.models import General
from sanmou_sim.skills import _calibrated_value


def general(force: float = 100, intellect: float = 300, command: float = 300) -> General:
    return General("测试", 10000, force, intellect, command, 100, [])


def test_text_baseline_calibrations() -> None:
    actor = general(intellect=1, command=1)
    assert math.isclose(
        _calibrated_value(actor, {"calibrated_formula": {"stat": "智力", "base": 26, "coefficient": 0.00177653}}, "value", 26),
        26 * (1 + 0.00177653),
    )
    assert math.isclose(
        _calibrated_value(actor, {"calibrated_formula": {"stat": "统率", "base": 80, "coefficient": 0.00086093}}, "value", 80),
        80 * (1 + 0.00086093),
    )


def test_huangfu_multiplier_exponent_calibration() -> None:
    actor = general(command=344.33)
    value = _calibrated_value(
        actor,
        {
            "calibrated_formula": {
                "stat": "统率",
                "base": 0.12,
                "coefficient": 0.0107076,
                "multiplier_exponent": 0.37909,
            },
        },
        "value",
        0.12,
    )
    assert math.isclose(value, 0.215530623, rel_tol=1e-6)
