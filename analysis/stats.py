"""Confidence intervals.

- Proportions (like decision accuracy) use the Wilson score interval. Unlike the
  simple "p ± 1.96·sqrt(p(1-p)/n)" interval, Wilson stays inside [0, 1] and still
  behaves sensibly at small n or when p is 0 or 1.
- Means (like return per hand) use the normal approximation:
  mean ± 1.96 · s / sqrt(n), where s is the sample standard deviation.
"""

import math
import statistics
from dataclasses import dataclass

Z_95 = 1.96  # z-score for a two-sided 95% interval


def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for successes / trials. Returns (nan, nan) when trials is 0."""
    if trials == 0:
        return math.nan, math.nan
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    half_width = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


@dataclass(frozen=True)
class Proportion:
    """k out of n, with its rate and Wilson 95% interval."""

    k: int
    n: int

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else math.nan

    @property
    def low(self) -> float:
        return wilson_interval(self.k, self.n)[0]

    @property
    def high(self) -> float:
        return wilson_interval(self.k, self.n)[1]


@dataclass(frozen=True)
class MeanCI:
    """A sample mean with a normal-approximation 95% interval."""

    n: int
    mean: float
    half_width: float  # nan when n < 2 (no spread can be estimated)

    @property
    def low(self) -> float:
        return self.mean - self.half_width

    @property
    def high(self) -> float:
        return self.mean + self.half_width


def mean_with_ci(values: list[float], z: float = Z_95) -> MeanCI:
    """Mean ± z · (sample sd) / sqrt(n)."""
    n = len(values)
    if n == 0:
        return MeanCI(0, math.nan, math.nan)
    mean = statistics.fmean(values)
    if n < 2:
        return MeanCI(n, mean, math.nan)
    return MeanCI(n, mean, z * statistics.stdev(values) / math.sqrt(n))
