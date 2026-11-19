"""Stream approved, normalised network metadata into AIGovKit."""

import argparse
import json
import os
import sys

import httpx
from pydantic import ValidationError

from aigovkit.device_discovery import DomainSignal, Observation
from aigovkit.provider_discovery import https_endpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("devices", "domains"))
    args = parser.parse_args()
    model, path = (
        (Observation, "/v1/device-observations")
        if args.kind == "devices"
        else (DomainSignal, "/v1/device-domain-signals")
    )
    processed = 0
    try:
        base = https_endpoint("AIGOVKIT_PASSIVE_API")
        key = os.environ["AIGOVKIT_PASSIVE_OBSERVER_KEY"]
        if len(key) < 32:
            raise ValueError("Configure a scoped observer key.")
        with httpx.Client(
            headers={"X-API-Key": key},
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            while line := sys.stdin.buffer.readline(8193):
                if len(line) > 8192:
                    raise ValueError("Observation line exceeds the size limit.")
                if not line.strip():
                    continue
                observation = model.model_validate_json(line)
                response = client.post(
                    base + path, json=observation.model_dump(mode="json")
                )
                response.raise_for_status()
                processed += 1
    except (httpx.HTTPError, KeyError, ValueError, ValidationError):
        parser.exit(1, f"Metadata intake stopped after {processed} accepted records.\n")
    print(json.dumps({"accepted": processed}))


if __name__ == "__main__":
    main()
