import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import httpx
from azure.identity import AzureCliCredential
from fastapi import Body, Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from examples import EXAMPLES
from models import ApiVersion, PlacementRequest, PlacementResponse, Region
from service import CACHE_TTL, SUBSCRIPTION, PlacementService, Result

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        UUID(SUBSCRIPTION)
    except ValueError as exc:
        raise RuntimeError("Set AZURE_SUBSCRIPTION_ID to a valid subscription GUID before starting.") from exc
    credential = AzureCliCredential(subscription=SUBSCRIPTION, process_timeout=30)
    service = PlacementService(credential, httpx.Client(timeout=60, follow_redirects=False))
    app.state.service = service
    try:
        yield
    finally:
        service.close()
        credential.close()


app = FastAPI(
    title="Compute Placement Scores - Live Azure PoC",
    version="0.1.0",
    description=(
        "Local-only ARM test harness pinned to the configured AZURE_SUBSCRIPTION_ID. "
        "No compute resources are created. Uses the server's Azure CLI login, not a browser token. "
        "All public options are exposed below; internal S2S options are intentionally excluded. "
        "The spec's current preview is 2026-10-05-preview. Check /api/provider for availability. "
        "Select versions explicitly: there is no fallback. Successful scores are cached for "
        "15 minutes. refresh=true consumes another Azure request. See /api/config for caveats."
    ),
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    LOGGER.warning("Rejected invalid request: %s", request.url.path)
    return JSONResponse(status_code=400, content={
        "error": {
            "code": "InvalidParameter",
            "message": "Request failed local schema validation; no Azure call was made.",
            "details": [
                {"target": ".".join(map(str, error["loc"])), "message": error["msg"]}
                for error in exc.errors()
            ],
        }
    })


def get_service(request: Request) -> PlacementService:
    return request.app.state.service


Service = Annotated[PlacementService, Depends(get_service)]
Payload = Annotated[PlacementRequest, Body(openapi_examples=EXAMPLES)]
Version = Annotated[
    ApiVersion, Query(alias="api-version", description="Explicit contract; never auto-falls back.")
]
ResourceGroup = Annotated[
    str, Path(min_length=1, max_length=90, pattern=r"^[\w().-]*[\w()-]$")
]
RESPONSES = {
    200: {"model": PlacementResponse, "description": "Unmodified Azure response (or cached result)."},
    400: {"description": "Local validation error or unmodified Azure validation error."},
    401: {"description": "Azure CLI authentication failure or Azure Unauthorized."},
    403: {"description": "Missing RBAC or preview access."},
    429: {"description": "Azure throttling. Retry-After is preserved; no automatic retry."},
    500: {"description": "Upstream Azure service error."},
    502: {"description": "Connection failure, non-JSON success, or upstream contract mismatch."},
    504: {"description": "Azure request timeout."},
}


def response(result: Result) -> JSONResponse:
    return JSONResponse(status_code=result.status, content=result.body, headers=result.headers)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/docs")


@app.get("/health", tags=["Local"])
def health():
    """Local liveness only. Does not verify Azure authentication or consume an ARM call."""
    return {"status": "ok"}


@app.get("/api/config", tags=["Local"])
def config():
    return {
        "subscriptionId": SUBSCRIPTION,
        "authentication": "Azure CLI identity of the local server process",
        "specVersion": "2026-10-05-preview",
        "cacheTtlSeconds": CACHE_TTL,
        "cacheMaxEntries": 256,
        "cachePersistence": "Memory only; cleared on restart; use one server worker",
        "caveats": [
            "Preview access is required; RBAC alone does not grant API access.",
            "Use Compute Recommendations Role as the least-privileged documented role.",
            "Scores are not allocation guarantees and may be stale after 15-30 minutes.",
            "placementPreference is comparable only within one response; higher is better.",
            "Current preview: 1-3 sizes, count 1-100; locations optional, maximum 5.",
            "Legacy: 1-20 sizes, count 1-1000; 1-5 locations required.",
            "Storage-aware scoring requires separate caller and region onboarding.",
            "A storage payload may be validated but ignored; check for storageProfile in response.",
            "Unsupported VM families, SKU mappings, quota, ODCR existence and RBAC are validated by Azure.",
            "Internal S2S, physical zone display and subscription-check bypass are out of scope.",
            "Spot scoring and deprecated diagnostics routes are not part of this PoC.",
            "Never expose this unauthenticated harness beyond loopback.",
        ],
    }


@app.post("/api/scores/{region}", tags=["Scores"], responses=RESPONSES)
def subscription_scores(
    region: Region, body: Payload, service: Service,
    api_version: Version = "2026-10-05-preview",
    refresh: bool = False,
):
    """Generate subscription-scoped on-demand scores. Defaults to the specification version."""
    return response(service.generate(body, region, api_version, refresh=refresh))


@app.post(
    "/api/resource-groups/{resource_group}/scores/{region}",
    tags=["Scores"], responses=RESPONSES,
)
def resource_group_scores(
    resource_group: ResourceGroup, region: Region, body: Payload, service: Service,
    api_version: Version = "2026-10-05-preview",
    refresh: bool = False,
):
    """Generate resource-group-scoped scores for an existing group; does not create one."""
    return response(service.generate(body, region, api_version, resource_group, refresh))


@app.get("/api/provider", tags=["Access diagnostics"])
def provider(service: Service):
    """Read live Compute provider metadata, including advertised versions and locations."""
    return response(service.provider())


@app.get("/api/features/{feature}", tags=["Access diagnostics"])
def feature(
    feature: Annotated[
        str, Path(pattern=r"^(ComputePlacementScores|ComputePlacementScoresGA)$")
    ],
    service: Service,
):
    """Read preview registration state only. Does not register features or change RBAC."""
    return response(service.feature(feature))
