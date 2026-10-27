# Compute Placement Scores API PoC

Local FastAPI/Swagger test harness for the Compute Placement Scores API.
Calls the real public Azure Resource Manager API in the subscription configured
through `AZURE_SUBSCRIPTION_ID`. It does **not** simulate capacity scores,
deploy VMs, create resource groups, register features, or change role assignments.

## Run on Windows

Requires Python 3.11+ and Azure CLI on PATH.

```powershell
git clone https://github.com/jvargh/compute-recommendation-svc.git
Set-Location .\compute-recommendation-svc\compute-placement-scores-api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
az login
$env:AZURE_SUBSCRIPTION_ID = '<your-subscription-guid>'
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs and expand a Scores operation. Choose an example,
click **Try it out**, explicitly select `api-version`, and execute.
ReDoc is at `/redoc`; the exportable OpenAPI schema is at `/openapi.json`.
No token needs to be pasted into Swagger: the backend uses `AzureCliCredential`
pinned to the configured subscription. Startup fails if `AZURE_SUBSCRIPTION_ID`
is missing or is not a valid GUID. Tokens are held only in server memory.
The lock file records the exact verified dependency set; `requirements.txt`
contains the direct dependency constraints for intentional updates.

**Keep this harness on loopback.** It has no client authentication and uses the
server operator's Azure identity. It is not a production or multi-user service.
Run a single worker so the cache is shared by all requests.

## Version and access requirements

The default contract is `2026-10-05-preview`. Availability depends on the
service rollout, subscription and region. Azure may return HTTP 400
`NoRegisteredProviderFound` for an unavailable version. Read `/api/provider`
and explicitly select an advertised version such as `2026-09-05-preview`.
There is deliberately **no automatic fallback** or response conversion.

Access may be granted through `Microsoft.Compute/ComputePlacementScores`,
`Microsoft.Compute/ComputePlacementScoresGA`, or an applicable allow-list.
Registering the GA flag is not required when another documented access path
applies. Nothing is registered by this PoC.
Use `/api/provider` and `/api/features/...` to read current state.
The least-privileged documented role is **Compute Recommendations Role**.
Private-preview allow-listing/feature access is also required.

## Operations

| Route | Purpose |
|---|---|
| `POST /api/scores/{region}` | Subscription-scoped placement scores |
| `POST /api/resource-groups/{resource_group}/scores/{region}` | Scores at an existing resource-group scope |
| `GET /api/provider` | Live Compute provider metadata, including supported versions/locations |
| `GET /api/features/ComputePlacementScores` | Read original preview registration |
| `GET /api/features/ComputePlacementScoresGA` | Read broader-access flag registration |
| `GET /api/config` | Subscription, contracts, cache configuration, caveats |
| `GET /health` | Local liveness only; does not call Azure |

Both POST routes accept query parameters:

- `api-version`: explicit supported contract, default `2026-10-05-preview`.
- `refresh`: default `false`; `true` bypasses the score cache and consumes another call.

Subscription scope maps to:

```text
POST https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Compute/locations/{region}/placementScores/regular/generate?api-version={api-version}
```

The resource-group variant inserts `/resourceGroups/{resourceGroupName}` after
the subscription. The subscription is fixed server-side and cannot be overridden
through a request. Regions use ARM names such as `eastus`, not display names.

### Request surface

All documented **public ARM** fields are represented in the OpenAPI schemas:

- `desiredLocations`, `desiredSizes[].sku`, `desiredCount`, `availabilityZones`.
- `storageProfile.osDisk.managedDisk.storageAccountType`.
- `storageProfile.dataDisks[].managedDisk.storageAccountType`.
- `additionalProperties.vmssOrchestrationMode` (`flex` / `uniform`).
- `additionalProperties.vmssSinglePlacementGroup`.
- `additionalProperties.vmssPlatformFaultDomainCount`.
- `additionalProperties.additionalCapacityPools.capacityReservationGroup`.
- `additionalProperties.ultraSSDEnabled`.
- `additionalProperties.zonePlacementPolicy`
  (`Any`, `PlatformBestEffortAlignment`, `Auto`; case-insensitive input).
- `additionalProperties.vmTags`.
- `additionalProperties.mapFlexToStandardSizes`.
- `additionalProperties.enableFlowVmSizes`.

Swagger includes examples for regional/zonal results, URI-region defaulting,
storage, uniform VMSS, both size-mapping modes, tags/zone policy, and ODCR pools.
Replace the ODCR placeholder with an **existing** capacity reservation group ID.
Use an actual mapped flex SKU when exercising flex mapping.

| Contract | Regions | Sizes | Count | Score / quota |
|---|---|---|---|---|
| `2026-10-05-preview` | Omitted/empty defaults to URI region; max 5 | 1-3 | 1-100 | `InsufficientQuota` score, required `placementPreference`, no `isQuotaAvailable` |
| Legacy versions | Required, 1-5 | 1-20 | 1-1000 | Optional `isQuotaAvailable`; `placementPreference` only for onboarded callers |

Legacy versions exposed: `2026-09-05-preview`, `2026-05-05-preview`,
`2025-06-05`, `2025-06-05-preview`, `2025-02-01-preview`, `2024-06-01-preview`.
Provider metadata is authoritative for regional/version availability.

Local validation rejects wrong JSON types, unknown fields, invalid disk types,
more than 10 data disks, missing OS disk settings, invalid/empty tag keys or
non-string values, conflicting mapping flags, and single-placement-group mode
without uniform orchestration. Disk type matching is case-insensitive and the
supplied casing is preserved. Empty/omitted data-disk types are skipped as in the
specification. Explicit null values are not accepted where a concrete scalar
is required.

Unsupported VM families, real SKU/region availability, service-configured disk
limits, VMSS constraints, mapping data, pool existence, quota and RBAC remain
Azure-authoritative; this client does not invent local capacity/mapping data.

### Response and error behavior

Successful Azure JSON is returned unchanged. All six current score values are
recognized: `High`, `Medium`, `Low`, `InsufficientQuota`,
`RestrictedSkuNotAvailable`, `DataNotFoundOrStale`.

`placementPreference` is 0-10, higher is better, and only comparable **within a
single response**, not across different calls or cached requests. Scores are not
allocation guarantees. Do not treat absent legacy quota information as `true`.

Storage scoring needs separate caller/region onboarding. Azure may validate a
storage payload but ignore it for scoring; check whether `storageProfile` was
echoed. This harness never fabricates the missing echo.

- Local validation returns HTTP 400 with an ARM-style `error` object and details.
- Azure JSON errors retain their status and body (including 400/401/403/429/500).
- `Retry-After`, Azure request/correlation IDs and selected rate-limit headers
  are preserved. `x-poc-client-request-id` identifies the original Azure request.
- Authentication failure is 401; connection failure is 502; timeout is 504.
- A malformed successful Azure response or version-contract mismatch is an
  explicit 502, not a fake successful score. Contract mismatches include the
  upstream body for inspection.
- No automatic retries, feature registration, version fallback, or provisioning.

### Cache / rate limits

Successful results are cached for **900 seconds (15 minutes)**. Keys include
scope, URI region, version and the complete request payload. Region/SKU order
is preserved because it affects response preference order.
The in-memory cache has at most 256 entries and resets on process restart.
Concurrent identical requests share one upstream call. Cache headers:

- `x-poc-cache: MISS` for a live request.
- `x-poc-cache: HIT` and `x-poc-cache-ttl-seconds` for a cached response.

Errors are never cached. The preview has a very small daily call allowance:
do not run a large live test matrix or repeatedly use `refresh=true`.
Use offline tests for validation/error scenarios.

## Example live request

With the local server running:

```powershell
$body = @{
    desiredLocations = @('eastus')
    desiredSizes = @(@{ sku = 'Standard_D2_v2' })
    desiredCount = 1
    availabilityZones = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post `
    -Uri 'http://127.0.0.1:8000/api/scores/eastus?api-version=2026-09-05-preview' `
    -ContentType 'application/json' -Body $body
```

## Verification

Subscription-specific live outcomes are not included in this repository.
This is not a claim that every optional Azure capability is enabled. ODCR
requires an existing reservation group, mappings require appropriate SKUs, and
the current preview requires service rollout. These surfaces are exposed and
tested offline; exercise live capabilities only within your authorized environment.

Offline tests use a mocked HTTP transport and do not consume Azure calls:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

The explicit live smoke runner uses the same FastAPI routes and real CLI
authentication. It checks both feature registrations, issues one zonal score
request, then verifies a repeated request is served from cache. It exits nonzero
on errors and does not retry failed scoring calls.

```powershell
.\.venv\Scripts\python.exe smoke.py --live --api-version 2026-09-05-preview --output live-results.json
# Optional: also consume one score call at an existing resource-group scope:
.\.venv\Scripts\python.exe smoke.py --live --api-version 2026-09-05-preview --resource-group EXISTING-GROUP
```

Live evidence is local and ignored by source control. It contains actual
subscription-specific responses and request IDs, but no access tokens.
Keep the source document and live results within your authorized environment:
preview access and specification materials may be subject to NDA requirements.

## Deliberate scope

As agreed, this covers public ARM functionality only. The Microsoft-internal
S2S endpoint, certificate/private-network setup, physical-zone display,
`BypassSubscriptionChecks`, Spot scoring, and deprecated diagnostics routes
are not exposed. A client cannot derive live placement scores from the spec
alone; Azure is always the authority.
