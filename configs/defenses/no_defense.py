"""Baseline: no Spectre defense. Hook point for the --defense flag."""


def apply(system, cpu):
    """Leave the core unmodified."""
    return
