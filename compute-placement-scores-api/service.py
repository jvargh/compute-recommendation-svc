import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

import httpx
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from pydantic import ValidationError

from models import PlacementRequest, PlacementResponse

LOGGER = logging.getLogger(__name__)
ARM = "https://management.azure.com"
SUBSCRIPTION = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
CACHE_TTL = 900
FORWARDED_HEADERS = (
    "retry-after", "x-ms-request-id", "x-ms-correlation-request-id",
    "x-ms-ratelimit-remaining-subscription-reads",
    "x-ms-ratelimit-remaining-subscription-writes",
)


class Credential(Protocol):
    def get_token(self, *scopes: str) -> AccessToken: ...


@dataclass
class Result:
    status: int
    body: object
    headers: dict[str, str]


class PlacementService:
    def __init__(
        self, credential: Credential, client: httpx.Client,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.credential = credential
        self.client = client
        self.clock = clock
        self.cache: OrderedDict[str, tuple[float, Result]] = OrderedDict()
        self.lock = RLock()
        self.token: AccessToken | None = None

    def close(self) -> None:
        self.client.close()

    def error(self, status: int, code: str, message: str) -> Result:
        LOGGER.warning("%s: %s", code, message)
        return Result(status, {"error": {"code": code, "message": message}}, {})

    def request(self, method: str, path: str, **kwargs: object) -> Result:
        try:
            with self.lock:
                if self.token is None or self.token.expires_on <= time.time() + 300:
                    self.token = self.credential.get_token(f"{ARM}/.default")
                token = self.token.token
        except ClientAuthenticationError:
            return self.error(
                401, "LocalAzureAuthenticationFailed",
                "Azure CLI authentication failed. Run az login for the target subscription.",
            )
        request_id = str(uuid4())
        try:
            response = self.client.request(
                method, f"{ARM}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "x-ms-client-request-id": request_id,
                    "x-ms-return-client-request-id": "true",
                },
                **kwargs,
            )
        except httpx.TimeoutException:
            return self.error(504, "AzureTimeout", "Azure request timed out; no automatic retry.")
        except httpx.RequestError:
            return self.error(502, "AzureConnectionFailed", "Could not connect to Azure ARM.")
        headers = {
            key: response.headers[key] for key in FORWARDED_HEADERS if key in response.headers
        }
        headers["x-poc-client-request-id"] = request_id
        try:
            body = response.json()
        except ValueError:
            LOGGER.warning("Azure returned non-JSON, status=%s request=%s", response.status_code, request_id)
            return Result(
                response.status_code if response.is_error else 502,
                {"error": {
                    "code": "AzureNonJsonResponse",
                    "message": "Azure returned a non-JSON response.",
                    "upstreamStatus": response.status_code,
                }},
                headers,
            )
        if response.is_error:
            LOGGER.warning("Azure HTTP %s request=%s", response.status_code, request_id)
        if response.status_code == 401:
            with self.lock:
                self.token = None
        return Result(response.status_code, body, headers)

    def generate(
        self, body: PlacementRequest, region: str, version: str,
        resource_group: str | None = None, refresh: bool = False,
    ) -> Result:
        try:
            body.check_version(version)
        except ValueError as exc:
            return self.error(400, "ParameterValueInvalid", str(exc))
        path = f"/subscriptions/{SUBSCRIPTION}"
        if resource_group is not None:
            path += f"/resourceGroups/{quote(resource_group, safe='')}"
        path += f"/providers/Microsoft.Compute/locations/{region}/placementScores/regular/generate"
        payload = body.payload()
        key = json.dumps([path, version, payload], sort_keys=True, separators=(",", ":"))
        with self.lock:
            now = self.clock()
            cached = self.cache.get(key)
            if cached and cached[0] > now and not refresh:
                result = cached[1]
                return Result(result.status, result.body, {
                    **result.headers, "x-poc-cache": "HIT",
                    "x-poc-cache-ttl-seconds": str(max(0, int(cached[0] - now))),
                })
            result = self.request("POST", path, params={"api-version": version}, json=payload)
            if result.status == 200:
                try:
                    parsed = PlacementResponse.model_validate(result.body)
                    parsed.check_version(version)
                except (ValidationError, ValueError):
                    LOGGER.error("Azure response violates selected contract, version=%s", version)
                    return Result(502, {
                        "error": {
                            "code": "UpstreamContractMismatch",
                            "message": "Azure response does not match the selected API contract.",
                        },
                        "upstreamResponse": result.body,
                    }, result.headers)
                self.cache[key] = (self.clock() + CACHE_TTL, result)
                self.cache.move_to_end(key)
                while len(self.cache) > 256:
                    self.cache.popitem(last=False)
            return Result(result.status, result.body, {**result.headers, "x-poc-cache": "MISS"})

    def provider(self) -> Result:
        return self.request(
            "GET", f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Compute",
            params={"api-version": "2021-04-01"},
        )

    def feature(self, name: str) -> Result:
        return self.request(
            "GET", f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Features"
            f"/providers/Microsoft.Compute/features/{name}",
            params={"api-version": "2021-07-01"},
        )
