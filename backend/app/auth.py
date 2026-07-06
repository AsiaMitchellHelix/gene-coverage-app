"""
SAML SSO middleware using python3-saml.

Endpoints:
  GET  /saml/metadata  — SP metadata XML
  POST /saml/acs       — Assertion Consumer Service
  GET  /saml/logout    — SLO (optional)

After a successful ACS, a signed JWT is set as an HttpOnly cookie.
All other routes require a valid JWT cookie (verified by require_user).
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from app.config import settings

_COOKIE_NAME = "gcov_session"


def _saml_settings() -> dict:
    return {
        "sp": {
            "entityId": settings.saml_sp_entity_id,
            "assertionConsumerService": {
                "url": settings.saml_sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            # Loaded dynamically from IdP metadata URL at startup; populated by load_idp_metadata()
        },
        "strict": True,
        "debug": False,
    }


_cached_saml_settings: dict | None = None


async def load_idp_metadata() -> None:
    """Fetch IdP metadata and merge into SAML settings. Called at startup."""
    import httpx
    global _cached_saml_settings
    base = _saml_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(settings.saml_idp_metadata_url, timeout=10)
        resp.raise_for_status()
    idp_data = OneLogin_Saml2_Utils.get_metadata_from_string(resp.text)
    base["idp"] = idp_data
    _cached_saml_settings = base


def _build_saml_auth(request: Request) -> OneLogin_Saml2_Auth:
    req = {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", ""),
        "server_port": str(request.url.port or ""),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": {},
    }
    return OneLogin_Saml2_Auth(req, _cached_saml_settings)


def _issue_jwt(email: str) -> str:
    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _verify_jwt(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


async def saml_metadata(request: Request) -> Response:
    auth = _build_saml_auth(request)
    metadata = auth.get_settings().get_sp_metadata()
    return Response(content=metadata, media_type="application/xml")


async def saml_acs(request: Request) -> Response:
    form = await request.form()
    req_data = {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", ""),
        "server_port": str(request.url.port or ""),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": dict(form),
    }
    auth = OneLogin_Saml2_Auth(req_data, _cached_saml_settings)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        raise HTTPException(status_code=400, detail=f"SAML error: {errors}")

    email = auth.get_nameid()
    token = _issue_jwt(email)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        _COOKIE_NAME, token, httponly=True, secure=True, samesite="lax"
    )
    return response


def require_user(gcov_session: Annotated[str | None, Cookie()] = None) -> str:
    if not gcov_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = _verify_jwt(gcov_session)
        return payload["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
