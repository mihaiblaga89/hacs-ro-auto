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
        """Fetch vignette details for one car."""
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
            async with asyncio.timeout(20):
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
        """Return the check endpoint URL."""
        if self._api_url.endswith("/rca/check"):
            return self._api_url
        return f"{self._api_url}/rca/check"

    def _auth_header(self) -> str:
        token = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode(
            "ascii"
        )
        return f"Basic {token}"

    async def async_check(self, *, plate: str) -> dict[str, Any]:
        """Check RCA status for a plate."""
        headers = {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {"plate": plate.strip().upper()}

        try:
            async with asyncio.timeout(60):
                async with self._session.post(
                    self._endpoint(),
                    json=body,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise RuntimeError("Timed out while calling RCA API") from err
        except ClientResponseError as err:
            raise RuntimeError(f"RCA API returned {err.status} for {plate}") from err
        except (ClientError, ValueError) as err:
            raise RuntimeError("Failed to parse RCA API response") from err

        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected RCA API response shape")

        return payload


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
        """Return the check endpoint URL."""
        if self._api_url.endswith("/itp/check"):
            return self._api_url
        return f"{self._api_url}/itp/check"

    def _auth_header(self) -> str:
        token = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode(
            "ascii"
        )
        return f"Basic {token}"

    async def async_check(self, *, vin: str) -> dict[str, Any]:
        """Check ITP status for a VIN."""
        headers = {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {"vin": vin.strip().upper()}

        try:
            async with asyncio.timeout(60):
                async with self._session.post(
                    self._endpoint(),
                    json=body,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise RuntimeError("Timed out while calling ITP API") from err
        except ClientResponseError as err:
            raise RuntimeError(f"ITP API returned {err.status} for {vin}") from err
        except (ClientError, ValueError) as err:
            raise RuntimeError("Failed to parse ITP API response") from err

        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected ITP API response shape")

        return payload
