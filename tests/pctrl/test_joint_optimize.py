import csv

import pytest

from qtools.pctrl import joint_optimize as joint


@pytest.fixture(autouse=True)
def _restore_target():
    original = joint.ACTIVE_TARGET
    yield
    joint.apply_target(original)


def test_product_target_uses_single_linear_plane():
    joint.apply_target("HH")

    assert joint.MEASUREMENT_KEYS == [
        ("H", "H"), ("V", "V"), ("H", "V"), ("V", "H")
    ]
    assert joint.figure_of_merit({("H", "H"): 100.0}) == 1.0
    assert joint.figure_of_merit({("V", "V"): 100.0}) == -1.0


def test_hh_vv_uses_equal_linear_and_diagonal_weights():
    joint.apply_target("HH+VV")

    ideal = {
        ("H", "H"): 100.0,
        ("V", "V"): 100.0,
        ("D", "D"): 100.0,
        ("A", "A"): 100.0,
    }
    linear_only = {
        ("H", "H"): 100.0,
        ("V", "V"): 100.0,
        ("D", "D"): 50.0,
        ("A", "A"): 50.0,
        ("D", "A"): 50.0,
        ("A", "D"): 50.0,
    }

    assert joint.figure_of_merit(ideal) == 1.0
    assert joint.figure_of_merit(linear_only) == pytest.approx(0.5)


def test_hv_vh_flips_linear_target_but_keeps_diagonal_target():
    joint.apply_target("HV+VH")

    ideal = {
        ("H", "V"): 100.0,
        ("V", "H"): 100.0,
        ("D", "D"): 100.0,
        ("A", "A"): 100.0,
    }
    assert joint.figure_of_merit(ideal) == 1.0

    correlations = joint.plane_correlations(ideal)
    assert correlations == {"linear": 1.0, "diagonal": 1.0}


def test_save_counts_includes_plane_correlations(tmp_path):
    joint.apply_target("HH+VV")
    path = tmp_path / "counts.csv"
    counts = {
        ("H", "H"): 10.0,
        ("V", "V"): 10.0,
        ("D", "D"): 10.0,
        ("A", "A"): 10.0,
    }

    joint.save_counts(path, [(1, counts, 1.0)])
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0][:6] == ["evaluation", "J", "E_linear", "E_diagonal", "H,H", "V,V"]
    assert rows[1][:6] == ["1", "1.0", "1.0", "1.0", "10.0", "10.0"]
