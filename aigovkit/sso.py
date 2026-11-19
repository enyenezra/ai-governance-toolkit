"""Browser authorization-code sign-in using PKCE and encrypted cookies."""

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

router = APIRouter(prefix="/v1/sso", include_in_schema=False)
FLOW_COOKIE = "__Host-aigovkit-flow"
SESSION_COOKIE = "__Host-aigovkit-session"


def settings() -> tuple[str, str, str, str, Fernet]:
    authorization, endpoint, callback, client_id, key = (
        os.getenv("AIGOVKIT_SSO_" + name, "")
        for name in (
            "AUTHORIZATION_URL",
            "TOKEN_URL",
            "CALLBACK_URL",
            "CLIENT_ID",
            "COOKIE_KEY",
        )
    )
    try:
        for value in authorization, endpoint, callback:
            uri = urlsplit(value)
            if (
                uri.scheme != "https"
                or not uri.netloc
                or uri.username
                or uri.password
                or uri.fragment
                or uri.query
            ):
                raise ValueError
        if urlsplit(callback).path != "/v1/sso/callback" or not client_id:
            raise ValueError
        cipher = Fernet(key.encode())
    except ValueError:
        raise HTTPException(
            503, "Browser SSO is unavailable or misconfigured."
        ) from None
    return authorization, endpoint, callback, client_id, cipher


def exchange(endpoint: str, data: dict) -> str:
    try:
        result = httpx.post(endpoint, data=data, timeout=8, follow_redirects=False)
        result.raise_for_status()
        token = result.json().get("access_token")
        if not isinstance(token, str):
            raise TypeError
        return token
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(
            502, "The identity provider did not complete sign-in."
        ) from None


def cookie_token(request: Request) -> str | None:
    value = request.cookies.get(SESSION_COOKIE)
    if not value:
        return None
    _, _, callback, _, cipher = settings()
    check_origin(request, callback)
    try:
        return cipher.decrypt(value.encode(), ttl=3600).decode()
    except (InvalidToken, UnicodeError):
        raise HTTPException(401, "Browser session expired.") from None


def check_origin(request: Request, callback: str) -> None:
    uri = urlsplit(callback)
    origin = f"{uri.scheme}://{uri.netloc}"
    if (
        request.method not in {"GET", "HEAD"}
        and request.headers.get("Origin") != origin
    ):
        raise HTTPException(403, "Browser request origin is invalid.")


@router.get("/status")
def status() -> dict:
    try:
        settings()
    except HTTPException:
        return {"available": False}
    return {"available": True}


@router.get("/start")
def start() -> RedirectResponse:
    authorize, _, callback, client_id, cipher = settings()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": callback,
            "scope": os.getenv("AIGOVKIT_SSO_SCOPE", "openid"),
            "state": state,
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(authorize + "?" + query, status_code=303)
    response.set_cookie(
        FLOW_COOKIE,
        cipher.encrypt(json.dumps([state, verifier]).encode()).decode(),
        max_age=300,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback")
def complete(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    from aigovkit.tenancy import oidc_session

    _, endpoint, callback, client_id, cipher = settings()
    try:
        saved = request.cookies.get(FLOW_COOKIE, "")
        expected, verifier = json.loads(cipher.decrypt(saved.encode(), ttl=300))
    except (InvalidToken, ValueError):
        raise HTTPException(400, "The sign-in request expired.") from None
    if (
        not code
        or len(code) > 4096
        or not secrets.compare_digest(state.encode(), expected.encode())
    ):
        raise HTTPException(400, "The sign-in response did not match the request.")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if secret := os.getenv("AIGOVKIT_SSO_CLIENT_SECRET"):
        data["client_secret"] = secret
    token = exchange(endpoint, data)
    oidc_session(request, token, client_id=client_id)
    cookie = cipher.encrypt(token.encode()).decode()
    if len(cookie) > 3700:
        raise HTTPException(502, "The access token exceeds the browser session limit.")
    response = RedirectResponse("/workspace", status_code=303)
    response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="lax")
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=3600,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    if request.cookies.get(SESSION_COOKIE):
        _, _, callback, _, _ = settings()
        check_origin(request, callback)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, secure=True, httponly=True, samesite="strict"
    )
    return response
