"""VISTA-Sindh Earth Engine command line.

    python -m gee.run check                       # Day 6: auth, reduceRegion, tiny export
    python -m gee.run verify-assets               # Day 8: resolve dataset IDs -> configs/resolved_assets.json
    python -m gee.run smoke5                      # Day 10: 5-point S2 NDVI smoke test with leakage guard
    python -m gee.run upload-admin                # Sindh province/district/taluka assets
    python -m gee.run upload-zones FILE NAME      # village zones (vid, zone) -> <asset_root>/<NAME>/part_*
    python -m gee.run list-jobs
    python -m gee.run submit JOB [--zones NAME] [--years A B] [--regions ...] [--dry-run] [--limit N]
    python -m gee.run wave N [--dry-run]          # every job of wave N in configs/gee_jobs.yaml
    python -m gee.run status [--watch MINUTES]    # refresh manifest from Earth Engine
    python -m gee.run retry-failed [--dry-run]    # resubmit FAILED/CANCELLED jobs by re-running their job spec
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from .lib.common import ROOT, init, load_config
from .lib.manifest import Manifest, Submitter


def _ctx(args):
    from .jobs import Ctx
    return Ctx(zones=getattr(args, "zones", None),
               years=tuple(args.years) if getattr(args, "years", None) else None,
               regions=getattr(args, "regions", None) or [],
               zone_types=getattr(args, "zone_types", None))


def cmd_list_jobs(cfg, args):
    from .jobs import JOBS
    print(f"{'job':26s} {'day':14s} {'zones?':7s} summary")
    for name, j in JOBS.items():
        print(f"{name:26s} {j.day:14s} {'yes' if j.needs_zones else 'no':7s} {j.summary}")


def run_job(cfg, name: str, ctx, dry_run: bool, limit: int | None) -> Submitter:
    from .jobs import JOBS
    if name not in JOBS:
        raise SystemExit(f"unknown job {name}; see `list-jobs`")
    sub = Submitter(cfg, dry_run=dry_run, limit=limit)
    print(f"[{name}] day {JOBS[name].day}: {JOBS[name].summary}")
    JOBS[name].fn(cfg, ctx, sub)
    print(f"[{name}] submitted {sub.submitted}, skipped (done/active) {sub.skipped}")
    return sub


def cmd_submit(cfg, args):
    run_job(cfg, args.job, _ctx(args), args.dry_run, args.limit)


def cmd_wave(cfg, args):
    waves = yaml.safe_load((ROOT / "configs" / "gee_jobs.yaml").read_text())["waves"]
    wave = waves[str(args.n)] if str(args.n) in waves else waves[args.n]
    print(f"wave {args.n}: {wave['description']}")
    from .jobs import Ctx
    for spec in wave["jobs"]:
        ctx = Ctx(zones=spec.get("zones"), years=tuple(spec["years"]) if spec.get("years") else None,
                  regions=spec.get("regions") or [], zone_types=spec.get("zone_types"))
        try:
            run_job(cfg, spec["job"], ctx, args.dry_run, args.limit)
        except SystemExit as exc:
            print(f"  !! {spec['job']}: {exc}")


def _was_split(man, r) -> bool:
    """True if a zonal group was resubmitted as smaller chunk ranges (see zonal.split_failed)."""
    try:
        lo, hi = map(int, r["chunk"].split("-"))
    except ValueError:
        return False
    for o in man.rows:
        if o is r or o["job"] != r["job"] or o["year"] != r["year"]:
            continue
        try:
            a, b = map(int, o["chunk"].split("-"))
        except ValueError:
            continue
        if lo <= a <= b <= hi and (a, b) != (lo, hi):
            return True
    return False


def cmd_status(cfg, args):
    while True:
        counts = Manifest(cfg).refresh()
        print(time.strftime("%H:%M:%S"), dict(sorted(counts.items())))
        man = Manifest(cfg)
        # hide failures a later resubmission of the same description superseded
        failed = [r for r in man.rows if r["state"] in ("FAILED", "SUBMIT_FAILED")
                  and man.latest(r["description"]) is r]
        for r in failed[-10:]:
            note = "  [split into smaller tasks]" if _was_split(man, r) else ""
            print(f"  FAILED {r['description']}: {r['error'][:150]}{note}")
        if not args.watch:
            break
        time.sleep(args.watch * 60)


def cmd_retry_failed(cfg, args):
    """Re-run the job specs of failed tasks; the submitter skips everything already done/active."""
    man = Manifest(cfg)
    man.refresh()
    bad = [r for r in man.rows if r["state"] in ("FAILED", "CANCELLED", "SUBMIT_FAILED")]
    # a later successful/active resubmission of the same description supersedes a failure
    bad = [r for r in bad if man.latest(r["description"]) is r]
    jobs = sorted({r["job"] for r in bad})
    print(f"{len(bad)} failed tasks in jobs {jobs}")
    for r in bad:  # mark so the submitter does not skip them
        r["state"] = f"{r['state']}_RETRIED"
    man.save()
    print("Re-run the original commands (submit/wave) now; only failed tasks will be resubmitted.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m gee.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check").add_argument("--dry-run", action="store_true")
    sp.add_parser("verify-assets")
    sp.add_parser("smoke5")
    sp.add_parser("upload-admin").add_argument("--dry-run", action="store_true")
    up = sp.add_parser("upload-zones")
    up.add_argument("file", type=Path)
    up.add_argument("name", help="asset name under asset_root, e.g. zones/pilot_v0")
    up.add_argument("--dry-run", action="store_true")
    sp.add_parser("list-jobs")
    s = sp.add_parser("submit")
    s.add_argument("job")
    s.add_argument("--zones")
    s.add_argument("--zone-types", nargs="*", dest="zone_types")
    s.add_argument("--years", nargs=2, type=int)
    s.add_argument("--regions", nargs="*")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--limit", type=int)
    w = sp.add_parser("wave")
    w.add_argument("n")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--limit", type=int)
    st = sp.add_parser("status")
    st.add_argument("--watch", type=float, default=0, help="refresh every N minutes")
    sp.add_parser("retry-failed")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.cmd == "list-jobs":
        return cmd_list_jobs(cfg, args)
    init(cfg)
    from . import interactive as it
    if args.cmd == "check":
        it.check(cfg, dry_run=args.dry_run)
    elif args.cmd == "verify-assets":
        it.verify_assets(cfg)
    elif args.cmd == "smoke5":
        it.smoke5(cfg)
    elif args.cmd == "upload-admin":
        it.upload_admin(cfg, dry_run=args.dry_run)
    elif args.cmd == "upload-zones":
        it.upload_zones(cfg, args.file, args.name, dry_run=args.dry_run)
    elif args.cmd == "submit":
        cmd_submit(cfg, args)
    elif args.cmd == "wave":
        cmd_wave(cfg, args)
    elif args.cmd == "status":
        cmd_status(cfg, args)
    elif args.cmd == "retry-failed":
        cmd_retry_failed(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
