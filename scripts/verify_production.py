#!/usr/bin/env python3
"""Production smoke test script for SC1 (webapp) and SC2 (health endpoint) verification.

Usage:
    python scripts/verify_production.py \
        --webapp-url https://meeting-bot.example.com \
        --backend-url https://api.example.com

Exit code 0 if all checks pass, 1 if any fail.
"""

import argparse
import sys
from typing import Tuple

import httpx

TIMEOUT = 15.0


def check_webapp(url: str) -> Tuple[bool, str]:
    """SC1: Verify webapp returns HTTP 200 with content."""
    try:
        response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        if response.status_code == 200:
            length = len(response.content)
            return True, f"HTTP 200, {length} bytes"
        return False, f"HTTP {response.status_code}"
    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError as exc:
        return False, f"Connection failed: {exc}"
    except httpx.HTTPError as exc:
        return False, f"HTTP error: {exc}"


def check_health(url: str) -> Tuple[bool, str]:
    """SC2: Verify backend /health/ready returns HTTP 200 with healthy status."""
    health_url = url.rstrip("/") + "/health/ready"
    try:
        response = httpx.get(health_url, timeout=TIMEOUT, follow_redirects=True)
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"

        try:
            data = response.json()
        except Exception:
            return False, "Response is not valid JSON"

        status = data.get("status", "unknown")
        if status == "ready":
            return True, "All checks healthy"

        # Report degraded checks
        checks = data.get("checks", {})
        failed = [
            name for name, info in checks.items()
            if isinstance(info, dict) and info.get("status") != "ok"
        ]
        if failed:
            return False, f"Degraded: {', '.join(failed)}"
        return False, f"Status: {status}"

    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError as exc:
        return False, f"Connection failed: {exc}"
    except httpx.HTTPError as exc:
        return False, f"HTTP error: {exc}"


def print_results(results: list) -> None:
    """Print a formatted table of check results."""
    header = f"{'CHECK':<25} {'STATUS':<10} {'DETAIL'}"
    separator = "-" * 70
    print()
    print(separator)
    print(header)
    print(separator)
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name:<25} {status:<10} {detail}")
    print(separator)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify production deployment (SC1 webapp + SC2 health endpoint)"
    )
    parser.add_argument(
        "--webapp-url",
        required=True,
        help="URL of the meeting bot webapp (SC1 check)",
    )
    parser.add_argument(
        "--backend-url",
        required=True,
        help="URL of the backend API (SC2 health check)",
    )
    args = parser.parse_args()

    results = []

    # SC1: Webapp check
    passed, detail = check_webapp(args.webapp_url)
    results.append(("SC1: Webapp", passed, detail))

    # SC2: Health endpoint check
    passed, detail = check_health(args.backend_url)
    results.append(("SC2: Health Endpoint", passed, detail))

    print_results(results)

    all_passed = all(passed for _, passed, _ in results)
    if all_passed:
        print("All checks passed.")
    else:
        print("Some checks FAILED.")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
