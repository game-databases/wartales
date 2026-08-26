"""Pytest plumbing for the harvest test suite (spec-harvest.mdx §7).

Registers the `integration` marker and the `--run-integration` opt-in.
Integration smoke tests touch the real client paks on A: and the
local-only scratch TSVs; they are collected but skipped unless the flag
is passed, so the default `python -m pytest pipeline/tests -q` never
reads A:.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration smoke tests (need the Wartales client on A: "
        "and output/_recon-scratch/, both local to the data host)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: touches the real client paks + local scratch TSVs "
        "(spec-harvest.mdx §7); skipped unless --run-integration",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(
        reason="integration smoke: pass --run-integration (needs client paks "
        "+ scratch TSVs; unit suite never reads A:)"
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
