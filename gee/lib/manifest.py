"""Task manifest, throttled submission with retry/backoff, and status refresh (Days 26, 28).

The manifest (experiments/gee_task_manifest.csv) is the single record of every export:
job, product, year, chunk, description, task id, state, timestamps, destination, params.
Tasks whose description already COMPLETED or is READY/RUNNING are never resubmitted.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import time
from pathlib import Path

import ee

from .common import ROOT

FIELDS = ["job", "product", "year", "chunk", "description", "task_id", "state",
          "submitted_utc", "updated_utc", "destination", "params", "error"]
# Task API states (READY/RUNNING/COMPLETED) and Operations API states (PENDING/SUCCEEDED) both occur.
ACTIVE = {"READY", "RUNNING", "PENDING", "SUBMITTED", "CANCELLING"}
DONE = {"COMPLETED", "SUCCEEDED"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, cfg: dict):
        self.path = ROOT / cfg["gee"]["manifest"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: list[dict] = []
        if self.path.exists():
            with self.path.open(newline="") as f:
                self.rows = list(csv.DictReader(f))

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(self.rows)
        tmp.replace(self.path)

    def latest(self, desc: str) -> dict | None:
        hits = [r for r in self.rows if r["description"] == desc]
        return hits[-1] if hits else None

    def add(self, meta: dict) -> None:
        row = {k: "" for k in FIELDS}
        row.update({k: (json.dumps(v) if k == "params" else v) for k, v in meta.items() if k in FIELDS})
        self.rows.append(row)
        self.save()

    # ------------------------------------------------------------------ status

    def refresh(self) -> dict[str, int]:
        """Pull task states from Earth Engine and update the manifest."""
        states = {}
        for op in ee.data.listOperations():
            md = op.get("metadata", {})
            tid = op.get("name", "").split("/")[-1]
            states[tid] = (md.get("state", ""), op.get("error", {}).get("message", ""))
        counts: dict[str, int] = {}
        for r in self.rows:
            if r["task_id"] in states:
                st, err = states[r["task_id"]]
                if st and st != r["state"]:
                    r["state"], r["updated_utc"], r["error"] = st, _now(), err
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        self.save()
        return counts


def active_task_count() -> int:
    n = 0
    for op in ee.data.listOperations():
        if op.get("metadata", {}).get("state") in ACTIVE:
            n += 1
    return n


class Submitter:
    """Wraps task.start() with dedup, queue throttling and exponential backoff."""

    def __init__(self, cfg: dict, dry_run: bool = False, limit: int | None = None, force: bool = False):
        # force: resubmit even if the last run SUCCEEDED (after a method fix); active tasks are still skipped
        self.cfg, self.dry_run, self.limit, self.force = cfg, dry_run, limit, force
        self.manifest = Manifest(cfg)
        self.submitted = 0
        self.skipped = 0
        self._active_cache: tuple[float, int] = (0.0, 0)

    def _active(self) -> int:
        t, n = self._active_cache
        if time.time() - t > 30:
            n = active_task_count()
            self._active_cache = (time.time(), n)
        return n

    def _wait_for_queue(self) -> None:
        cap = self.cfg["gee"]["max_queued_tasks"]
        while self._active() >= cap:
            print(f"    queue full ({cap} active); waiting 60 s ...")
            time.sleep(60)
            self._active_cache = (0.0, 0)

    def submit(self, task: ee.batch.Task, *, job: str, product: str = "", year="", chunk="",
               destination: str = "", params: dict | None = None) -> bool:
        desc = task.config.get("description") or task.config.get("state", {}).get("description", "")
        prev = self.manifest.latest(desc)
        if prev and ((prev["state"] in DONE and not self.force) or prev["state"] in ACTIVE):
            self.skipped += 1
            return False
        if self.limit is not None and self.submitted >= self.limit:
            return False
        if self.dry_run:
            print(f"    [dry-run] {desc}")
            self.submitted += 1
            return True
        self._wait_for_queue()
        delay = 5
        for attempt in range(self.cfg["gee"]["submit_retries"] + 1):
            try:
                task.start()
                break
            except ee.EEException as exc:
                if attempt == self.cfg["gee"]["submit_retries"]:
                    print(f"    FAILED to submit {desc}: {exc}")
                    self.manifest.add(dict(job=job, product=product, year=year, chunk=chunk,
                                           description=desc, state="SUBMIT_FAILED",
                                           submitted_utc=_now(), error=str(exc), params=params or {}))
                    return False
                print(f"    submit error ({exc}); retry in {delay}s")
                time.sleep(delay)
                delay *= 2
        self.manifest.add(dict(job=job, product=product, year=year, chunk=chunk, description=desc,
                               task_id=task.id, state="READY", submitted_utc=_now(),
                               updated_utc=_now(), destination=destination, params=params or {}))
        self.submitted += 1
        self._active_cache = (self._active_cache[0], self._active_cache[1] + 1)
        print(f"    submitted {desc} ({task.id})")
        time.sleep(self.cfg["gee"]["submit_pause_s"])
        return True
