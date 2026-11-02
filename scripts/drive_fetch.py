"""List / download Earth Engine Drive exports (folders vista_gee_*) with the EE login's Drive scope.

    python scripts/drive_fetch.py list
    python scripts/drive_fetch.py get vista_gee_settlements data/village_inventory/settlements
    python scripts/drive_fetch.py get vista_gee_chirps_grid data/climate/chirps --pattern chirps_grid_
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import ee
import google.auth.transport.requests as gtr

API = "https://www.googleapis.com/drive/v3/files"


def _token(tries: int = 5) -> str:
    for i in range(tries):
        try:
            creds = ee.data.get_persistent_credentials()
            creds.refresh(gtr.Request())
            return creds.token
        except Exception as exc:  # token refresh hits the same flaky connection
            if i == tries - 1:
                raise
            print(f"  token retry {i + 1} after {exc}")
            time.sleep(5 * (i + 1))


def _get(url: str, token: str, tries: int = 5):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for i in range(tries):  # the connection here drops now and then
        try:
            return urllib.request.urlopen(req, timeout=300)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} after {exc}")
            time.sleep(5 * (i + 1))


def query(q: str, token: str, fields="files(id,name,size,mimeType,modifiedTime,parents)") -> list[dict]:
    out, page = [], None
    while True:
        params = {"q": q, "fields": f"nextPageToken,{fields}", "pageSize": 1000}
        if page:
            params["pageToken"] = page
        res = json.load(_get(f"{API}?{urllib.parse.urlencode(params)}", token))
        out += res.get("files", [])
        page = res.get("nextPageToken")
        if not page:
            return out


def folders(token: str, prefix="vista_gee") -> list[dict]:
    q = f"mimeType='application/vnd.google-apps.folder' and name contains '{prefix}' and trashed=false"
    return query(q, token)


def files_in(folder_ids: list[str], token: str) -> list[dict]:
    out = []
    for fid in folder_ids:
        out += query(f"'{fid}' in parents and trashed=false", token)
    return out


def download(f: dict, dest: Path, size: int, token: str, tries: int = 20) -> None:
    """Write to <dest>.part, resume with Range requests after drops, rename when complete."""
    part = dest.with_name(dest.name + ".part")
    dest.unlink(missing_ok=True)  # an earlier truncated copy
    for i in range(tries):
        have = part.stat().st_size if part.exists() else 0
        if have == size:
            break
        req = urllib.request.Request(f"{API}/{f['id']}?alt=media",
                                     headers={"Authorization": f"Bearer {token}", "Range": f"bytes={have}-"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, part.open("ab" if have else "wb") as out:
                if have and r.status != 206:  # server ignored Range: start over
                    out.truncate(0)
                while chunk := r.read(1 << 20):
                    out.write(chunk)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            print(f"  {dest.name}: drop at {have / 2**20:.1f} MB ({exc}); resuming")
            time.sleep(min(5 * (i + 1), 30))
            if i % 5 == 4:
                token = _token()
    if not part.exists() or part.stat().st_size != size:
        raise RuntimeError(f"{dest.name}: incomplete after {tries} tries")
    part.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    g = sub.add_parser("get")
    g.add_argument("folder")
    g.add_argument("dest", type=Path)
    g.add_argument("--pattern", default="")
    args = ap.parse_args()

    token = _token()
    fl = folders(token)
    if args.cmd == "list":
        by = {}
        for f in fl:
            by.setdefault(f["name"], []).append(f["id"])
        for name, ids in sorted(by.items()):
            fs = files_in(ids, token)
            mb = sum(int(f.get("size", 0)) for f in fs) / 2**20
            print(f"{name:32s} {len(fs):4d} files {mb:9.1f} MB" + (f"  ({len(ids)} folders)" if len(ids) > 1 else ""))
        return 0

    ids = [f["id"] for f in fl if f["name"] == args.folder]
    if not ids:
        print(f"no Drive folder {args.folder}")
        return 1
    args.dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files_in(ids, token):
        if args.pattern not in f["name"]:
            continue
        dest = args.dest / f["name"]
        size = int(f.get("size", -1))
        if dest.exists() and dest.stat().st_size == size:
            continue
        download(f, dest, size, token)
        n += 1
        print(f"  {dest}  {dest.stat().st_size / 2**20:.1f} MB")
    print(f"downloaded {n} file(s) to {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
