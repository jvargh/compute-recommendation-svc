"""Opt-in live checks. Starts an in-process harness, not a network listener."""

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from service import SUBSCRIPTION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Required: consume live Azure calls")
    parser.add_argument("--api-version", default="2026-09-05-preview")
    parser.add_argument("--region", default="eastus")
    parser.add_argument("--resource-group", help="Existing group; also test resource-group scope")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence file (no access tokens)")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this consumes the subscription's API allowance")
    report = {"subscriptionId": SUBSCRIPTION, "apiVersion": args.api_version, "checks": []}
    body = {
        "desiredLocations": [args.region],
        "desiredSizes": [{"sku": "Standard_D2_v2"}],
        "desiredCount": 1,
        "availabilityZones": True,
    }
    with TestClient(app) as client:
        for name in ("ComputePlacementScores", "ComputePlacementScoresGA"):
            result = client.get(f"/api/features/{name}")
            report["checks"].append({
                "name": name, "status": result.status_code, "body": result.json(),
            })
        routes = [f"/api/scores/{args.region}"]
        if args.resource_group:
            routes.append(f"/api/resource-groups/{args.resource_group}/scores/{args.region}")
        for route in routes:
            first = client.post(route, params={"api-version": args.api_version}, json=body)
            cached = (
                client.post(route, params={"api-version": args.api_version}, json=body)
                if first.status_code == 200 else None
            )
            report["checks"].append({
                "name": route, "status": first.status_code, "body": first.json(),
                "cache": cached.headers.get("x-poc-cache") if cached is not None else None,
                "cacheMatches": cached.json() == first.json() if cached is not None else False,
                "requestId": first.headers.get("x-ms-request-id"),
            })
            if first.status_code != 200:
                # Do not spend another scoring call after a failed live request.
                break
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if all(
        item["status"] == 200 and (
            "cache" not in item or (item["cache"] == "HIT" and item["cacheMatches"])
        ) for item in report["checks"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
