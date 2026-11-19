"""Run due policy reminders and incident intake from a deployment scheduler."""

import json
import os

import httpx

from aigovkit.provider_discovery import https_endpoint


def main():
    try:
        base = https_endpoint("AIGOVKIT_JOBS_API")
        headers = {"X-API-Key": os.environ["AIGOVKIT_JOBS_KEY"]}
        with httpx.Client(
            headers=headers, timeout=25, follow_redirects=False, trust_env=False
        ) as client:
            results = {}
            for task in ("review-reminders", "incident-alerts"):
                result = client.post(f"{base}/v1/{task}/run")
                result.raise_for_status()
                results[task] = result.json()
            print(json.dumps(results))
    except (KeyError, ValueError, httpx.HTTPError):
        raise SystemExit("Scheduled governance jobs could not complete.") from None


if __name__ == "__main__":
    main()
