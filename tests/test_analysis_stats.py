"""Tests for the confidence-interval helpers (analysis/stats.py)."""

import math

import pytest

from analysis.stats import mean_with_ci, wilson_interval


def test_wilson_matches_a_textbook_value():
    # 8 successes out of 10: the Wilson 95% interval is about (0.490, 0.943).
    low, high = wilson_interval(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-3)
    assert high == pytest.approx(0.9433, abs=1e-3)


def test_wilson_stays_inside_zero_and_one_at_the_edges():
    low, high = wilson_interval(0, 5)
    assert low == 0.0
    assert 0 < high < 1
    low, high = wilson_interval(5, 5)
    assert 0 < low < 1
    assert high == pytest.approx(1.0)


def test_wilson_with_no_trials_is_undefined():
    low, high = wilson_interval(0, 0)
    assert math.isnan(low) and math.isnan(high)


def test_mean_with_ci_uses_the_sample_standard_deviation():
    # values 1, -1, 1, -1: mean 0, sample sd = sqrt(4/3), half-width = 1.96 * sd / 2
    summary = mean_with_ci([1, -1, 1, -1])
    assert summary.n == 4
    assert summary.mean == 0
    assert summary.half_width == pytest.approx(1.96 * math.sqrt(4 / 3) / 2)
    assert summary.low == pytest.approx(-summary.half_width)
    assert summary.high == pytest.approx(summary.half_width)


def test_mean_with_ci_of_one_value_has_no_interval():
    summary = mean_with_ci([2.5])
    assert summary.mean == 2.5
    assert math.isnan(summary.half_width)


def test_mean_with_ci_of_nothing_is_undefined():
    summary = mean_with_ci([])
    assert summary.n == 0
    assert math.isnan(summary.mean)
