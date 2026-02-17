"""API client for erovinieta."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiohttp import ClientError, ClientResponseError, ClientSession

API_URL = "https://www.erovinieta.ro/vgncheck/api/findVignettes"
CACHE_BUSTER_PARAM = "cacheBuster"
DEFAULT_TIMEOUT_SECONDS = 240


def normalize_vignette_payload(data: Any) -> dict[str, Any]:
    """Normalize API response based on the JS contract.

    JS logic:
    - response.data is a list
    - valid vignette when list is not empty
    - values taken from response.data[0].nrAuto/.serieSasiu/.dataStop
    """
    items = data if isinstance(data, list) else []
    has_vignette = len(items) != 0
    first_item = items[0] if has_vignette and isinstance(items[0], dict) else {}

    nr_auto = first_item.get("nrAuto")
    serie_sasiu = first_item.get("serieSasiu")
    data_stop = first_item.get("dataStop")

    return {
        "vignetteValid": has_vignette,
        "vignetteExpiryDate": str(data_stop).strip() if data_stop is not None else None,
        "nrAuto": str(nr_auto).strip().upper() if nr_auto is not None else None,
        "serieSasiu": str(serie_sasiu).strip().upper() if serie_sasiu is not None else None,
        "dataStop": str(data_stop).strip() if data_stop is not None else None,
        "raw": data,
    }


class ErovinietaApiClient:
    """Thin async client for the public erovinieta endpoint."""

    def __init__(self, session: ClientSession) -> None:
        """Initialize the client."""
        self._session = session

    async def async_fetch_vignette(
        self,
        *,
        plate_number: str,
        vin: str,
    ) -> dict[str, Any]:
        """Fetch vignette details for one vehicle."""
        cache_buster = f"{int(datetime.now(tz=UTC).timestamp() * 1000)}-{uuid4().hex}"
        params = {
            "plateNumber": plate_number.strip().upper(),
            "vin": vin.strip().upper(),
            CACHE_BUSTER_PARAM: cache_buster,
        }
        headers = {
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        try:
            async with asyncio.timeout(DEFAULT_TIMEOUT_SECONDS):
                async with self._session.get(
                    API_URL,
                    params=params,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise RuntimeError("Timed out while calling erovinieta API") from err
        except ClientResponseError as err:
            raise RuntimeError(
                f"Erovinieta API returned {err.status} for {plate_number}/{vin}"
            ) from err
        except (ClientError, ValueError) as err:
            raise RuntimeError("Failed to parse erovinieta API response") from err

        return normalize_vignette_payload(payload)


class RcaApiClient:
    """Async client for a private RCA API."""

    def __init__(self, session: ClientSession, *, api_url: str, username: str, password: str) -> None:
        """Initialize the RCA client."""
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._username = username
        self._password = password

    def _endpoint(self) -> str:
        return _build_endpoint(self._api_url, "/rca/check")

    async def async_check(self, *, plate: str) -> dict[str, Any]:
        """Check RCA status for a plate."""
        body = {"plate": plate.strip().upper()}
        return await _post_basic_auth_json(
            self._session,
            url=self._endpoint(),
            username=self._username,
            password=self._password,
            body=body,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            error_prefix="RCA",
            context_id=plate,
        )


class ItpApiClient:
    """Async client for a private ITP API."""

    def __init__(
        self, session: ClientSession, *, api_url: str, username: str, password: str
    ) -> None:
        """Initialize the ITP client."""
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._username = username
        self._password = password

    def _endpoint(self) -> str:
        return _build_endpoint(self._api_url, "/itp/check")

    async def async_check(self, *, vin: str) -> dict[str, Any]:
        """Check ITP status for a VIN."""
        body = {"vin": vin.strip().upper()}
        return await _post_basic_auth_json(
            self._session,
            url=self._endpoint(),
            username=self._username,
            password=self._password,
            body=body,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            error_prefix="ITP",
            context_id=vin,
        )


def _build_endpoint(api_url: str, suffix: str) -> str:
    """Return endpoint URL, allowing either base URL or full endpoint URL."""
    api_url = api_url.rstrip("/")
    if api_url.endswith(suffix):
        return api_url
    return f"{api_url}{suffix}"


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


async def _post_basic_auth_json(
    session: ClientSession,
    *,
    url: str,
    username: str,
    password: str,
    body: dict[str, Any],
    timeout_seconds: int,
    error_prefix: str,
    context_id: str,
) -> dict[str, Any]:
    """POST JSON with Basic auth and return JSON dict."""
    headers = {
        "Authorization": _basic_auth_header(username, password),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with asyncio.timeout(timeout_seconds):
            async with session.post(url, json=body, headers=headers) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except TimeoutError as err:
        raise RuntimeError(f"Timed out while calling {error_prefix} API") from err
    except ClientResponseError as err:
        raise RuntimeError(f"{error_prefix} API returned {err.status} for {context_id}") from err
    except (ClientError, ValueError) as err:
        raise RuntimeError(f"Failed to parse {error_prefix} API response") from err

    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected {error_prefix} API response shape")

    return payload
