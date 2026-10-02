#!/usr/bin/env python3
"""Check that every resource URL in data/resources.json is still reachable.

Results are split by how much they prove:

- FAIL: the site answered 404/410 or the host does not exist. The resource is
  gone or moved; fix or remove it. Exits non-zero.
- WARN: timeouts, 5xx, rate limiting, or bot blocking (403/429). Many
  institutional sites refuse automated clients, so these need a human look but
  do not fail the run unless --strict is given.

Only the Python standard library is used.
"""

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "Mozilla/5.0 (compatible; awesome-sign-languages-link-check; +https://github.com/tbalbinodesa/awesome-sign-languages)"
GONE = {404, 410}
BLOCKED = {401, 403, 429, 999}


def check(url, timeout=25, attempts=2):
    """Return (status, detail) where status is 'ok', 'warn' or 'fail'."""
    detail = ""
    for _ in range(attempts):
        # Some servers reject HEAD, so fall back to GET.
        for method in ("HEAD", "GET"):
            request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return "ok", f"HTTP {response.status}"
            except urllib.error.HTTPError as error:
                if error.code in GONE:
                    return "fail", f"HTTP {error.code} (gone or moved)"
                detail = f"HTTP {error.code}" + (" (blocks automated clients?)" if error.code in BLOCKED else "")
            except urllib.error.URLError as error:
                reason = error.reason
                if isinstance(reason, socket.gaierror):
                    return "fail", f"host not found ({reason})"
                detail = f"unreachable ({reason})"
            except (TimeoutError, socket.timeout):
                detail = "timed out"
            except OSError as error:
                detail = f"error ({error})"
    return "warn", detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    resources = json.loads((ROOT / "data/resources.json").read_text(encoding="utf-8"))["resources"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda r: (r, *check(r["url"])), resources))

    failed = warned = 0
    for resource, status, detail in results:
        line = f"{status.upper():4} {resource['id']}: {resource['url']} - {detail}"
        if status == "fail":
            failed += 1
            print(f"::error::{line}")
        elif status == "warn":
            warned += 1
            print(f"::warning::{line}")
        else:
            print(line)
    print(f"{len(results)} checked, {failed} failed, {warned} warnings")
    return 1 if failed or (args.strict and warned) else 0


if __name__ == "__main__":
    sys.exit(main())
