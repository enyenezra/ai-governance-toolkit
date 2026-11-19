"""Verify an audit export against an independently trusted Ed25519 public key."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aigovkit.assurance import canonical


def verify(export: dict, public: Ed25519PublicKey) -> None:
    if (
        export["algorithm"] != "Ed25519"
        or export["key_fingerprint"]
        != hashlib.sha256(public.public_bytes_raw()).hexdigest()
    ):
        raise ValueError("Unexpected signing key or algorithm.")
    public.verify(
        base64.b64decode(export["signature"], validate=True),
        canonical(export["payload"]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("public_key", type=Path)
    args = parser.parse_args()
    try:
        key = serialization.load_pem_public_key(args.public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError
        verify(json.loads(args.export.read_bytes()), key)
    except (InvalidSignature, KeyError, OSError, ValueError, TypeError):
        parser.exit(1, "Audit signature verification failed.\n")
    print("Audit signature verified.")


if __name__ == "__main__":
    main()
