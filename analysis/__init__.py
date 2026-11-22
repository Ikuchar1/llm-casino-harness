"""Turns run logs (runs/<dir>/) into numbers, tables, charts and results.md.

Modules:
    stats     confidence intervals (Wilson for proportions, normal approx for means)
    loading   reads one run directory into a Run
    metrics   every metric, computed from the logged rows
    charts    the PNG figures for the paper
    report    results.md and the multi-run comparison table
"""
