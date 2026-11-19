"""Verify RFC 9068 access tokens with operator-provisioned public keys."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException

CHALLENGE = {"WWW-Authenticate": "Bearer"}
MAX_TOKEN_LENGTH = 8192
MAX_JWKS_BYTES = 262144
MAX_TOKEN_LIFETIME = 3600


def invalid_token() -> HTTPException:
    return HTTPException(401, "Invalid access token.", headers=CHALLENGE)


def verify_access_token(token: str, client_id: str | None = None) -> str:
    issuer = os.environ.get("AIGOVKIT_OIDC_ISSUER", "")
    audience = os.environ.get("AIGOVKIT_OIDC_AUDIENCE")
    filename = os.environ.get("AIGOVKIT_OIDC_JWKS_FILE")
    try:
        url = urlsplit(issuer)
    except ValueError:
        raise HTTPException(503, "OIDC verification is misconfigured.") from None
    if not issuer and not audience and not filename:
        raise invalid_token()
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not audience
        or not filename
    ):
        raise HTTPException(503, "OIDC verification is misconfigured.")
    if len(token) > MAX_TOKEN_LENGTH:
        raise invalid_token()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise invalid_token() from None
    kid = header.get("kid")
    if (
        header.get("alg") != "RS256"
        or header.get("typ") not in ("at+jwt", "application/at+jwt")
        or not isinstance(kid, str)
        or not kid
        or header.get("crit")
    ):
        raise invalid_token()

    try:
        with Path(filename).open("rb") as stream:
            public_keys = stream.read(MAX_JWKS_BYTES + 1)
        if len(public_keys) > MAX_JWKS_BYTES:
            raise ValueError("JWKS is too large.")
        entries = json.loads(public_keys)["keys"]
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) for entry in entries
        ):
            raise ValueError("Invalid JWKS layout.")
        matches = [entry for entry in entries if entry.get("kid") == kid]
        if not matches:
            raise invalid_token()
        if len(matches) != 1:
            raise ValueError("Ambiguous signing key.")
        selected = matches[0]
        if (
            selected.get("kty") != "RSA"
            or selected.get("use", "sig") != "sig"
            or selected.get("alg", "RS256") != "RS256"
            or "d" in selected
        ):
            raise invalid_token()
        key = jwt.PyJWK.from_dict(selected, algorithm="RS256").key
        if key.key_size < 2048:
            raise ValueError("RSA key is too small.")
    except (OSError, ValueError, KeyError, TypeError, jwt.PyJWTError):
        raise HTTPException(503, "OIDC verification keys are unavailable.") from None

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": ["iss", "aud", "sub", "exp", "iat", "jti", "client_id"],
                "strict_aud": True,
            },
            leeway=30,
        )
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError):
        raise invalid_token() from None
    issued, expires = claims["iat"], claims["exp"]
    sub = claims["sub"]
    if (
        type(issued) is not int
        or type(expires) is not int
        or not 0 < expires - issued <= MAX_TOKEN_LIFETIME
        or not isinstance(sub, str)
        or not sub
        or len(sub) > 255
        or not isinstance(claims["client_id"], str)
        or not claims["client_id"]
        or (client_id is not None and claims["client_id"] != client_id)
    ):
        raise invalid_token()
    return sub
