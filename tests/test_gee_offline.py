"""Offline trace of every Earth Engine job against a mocked `ee` module.

Catches Python-level errors (typos, wrong signatures, missing config keys) without
credentials. It cannot validate Earth Engine semantics: run `python -m gee.run submit
<job> --dry-run` and the pilot wave for that.

    python -m pytest tests/test_gee_offline.py -q      (or: python tests/test_gee_offline.py)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _mock_ee():
    ee = mock.MagicMock(name="ee")
    ee.EEException = type("EEException", (Exception,), {})
    ee.data.getAsset.return_value = {"type": "TABLE"}
    ee.data.listOperations.return_value = []
    return ee


def run_all_jobs():
    sys.modules["ee"] = _mock_ee()
    for name in [m for m in sys.modules if m.startswith("gee")]:
        del sys.modules[name]
    from gee.jobs import JOBS, Ctx
    from gee.lib.common import load_config
    from gee.lib.manifest import Submitter

    cfg = load_config()
    cfg["gee"]["submit_pause_s"] = 0
    errors = {}
    for name, job in JOBS.items():
        ctx = Ctx(zones="zones/test" if job.needs_zones else None, years=(2020, 2020))
        sub = Submitter(cfg, dry_run=True)
        try:
            job.fn(cfg, ctx, sub)
        except Exception as exc:  # noqa: BLE001 - report every failure
            errors[name] = repr(exc)
    return JOBS, errors


def test_all_jobs_build():
    jobs, errors = run_all_jobs()
    assert not errors, errors
    assert len(jobs) >= 20


if __name__ == "__main__":
    jobs, errors = run_all_jobs()
    print(f"{len(jobs)} jobs traced, {len(errors)} errors")
    for k, v in errors.items():
        print(f"  {k}: {v}")
