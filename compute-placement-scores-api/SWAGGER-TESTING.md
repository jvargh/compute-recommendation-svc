# Swagger testing guide

Use this guide to exercise the local PoC against the real Azure Compute
Placement Scores API. Swagger is an interactive client for this harness, not a
mock scoring service. Scoring calls consume the subscription's preview allowance.
No VMs, resource groups, role assignments, or feature registrations are created.

## 1. Start the harness

From the repository root, open PowerShell:

```powershell
Set-Location .\compute-placement-scores-api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
az login
$env:AZURE_SUBSCRIPTION_ID = '<your-subscription-guid>'
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

If the environment already exists, skip its creation and dependency installation.
Set the environment variable in the **same terminal** that starts the server.
Restart the server after changing the subscription; it is read at process startup.

Open http://127.0.0.1:8000/docs. The page title should be
**Compute Placement Scores - Live Azure PoC**.

There is no Swagger token-entry step: the server obtains an ARM token through
your Azure CLI login. Access requires both appropriate RBAC (the documented
least-privileged role is **Compute Recommendations Role**) and an applicable
preview feature registration or allow-list.

Keep the server bound to `127.0.0.1`. It has no client authentication and uses
the server operator's identity. Do not publish it to a shared network.

## 2. Run preflight checks

For each GET operation below, expand it, click **Try it out**, fill any required
parameter, then click **Execute**. Inspect the actual **Server response** code
and body, not the static **Responses** reference at the bottom of the operation.

| Operation | What to verify | Calls Azure? |
|---|---|---|
| `GET /health` | HTTP 200 and `{"status":"ok"}`. This proves local liveness only. | No |
| `GET /api/config` | The intended subscription ID, cache TTL of 900 seconds, and caveats. | No |
| `GET /api/provider` | HTTP 200; find `resourceTypes` entry `locations/placementScores`. Inspect its `apiVersions` and `locations`. | Yes |
| `GET /api/features/{feature}` | Test `ComputePlacementScores` and, if needed, `ComputePlacementScoresGA`; inspect `properties.state`. | Yes |

Do not assume both feature flags must be registered. An applicable allow-list
or another documented access path may grant access. Registration state alone
also does not prove that the caller has the required RBAC.

### Select a version explicitly

The default is `2026-10-05-preview`, the current specification contract.
Only use it live when Azure advertises it for this operation. Otherwise,
select a supported version, such as `2026-09-05-preview`, from the
`api-version` dropdown. The client never automatically falls back.

| Contract | Locations | Sizes | Desired count | Response differences |
|---|---|---|---|---|
| `2026-10-05-preview` | Omitted/empty defaults to URI region; max 5 | 1-3 | 1-100 | `placementPreference` required; quota shortage is `InsufficientQuota`; no `isQuotaAvailable` |
| Supported legacy versions | Required, 1-5 | 1-20 | 1-1000 | Optional `isQuotaAvailable`; `placementPreference` may be absent |

The Swagger schema displays the broader legacy limits. Current-preview limits
are additionally checked against the selected version before calling Azure.

## 3. Run a minimal subscription-scope test

1. Under **Scores**, expand `POST /api/scores/{region}`.
2. Click **Try it out**.
3. Enter an advertised ARM region name, for example `eastus`, in `region`.
4. Select an advertised `api-version`.
5. Leave `refresh` as `false`.
6. In the request body editor, paste:

```json
{
  "desiredLocations": ["eastus"],
  "desiredSizes": [{"sku": "Standard_D2s_v5"}],
  "desiredCount": 1,
  "availabilityZones": false
}
```

7. Click **Execute** once.
8. Under **Server response**, inspect:
   - Actual HTTP status.
   - Response body and each item in `placementScores`.
   - Response headers, particularly `x-poc-cache` and Azure request IDs.

The region and SKU above are examples, not promises of availability. Substitute
values appropriate for your subscription. The URI region chooses the API
endpoint and is the current-preview default scoring region; an explicit
`desiredLocations` list chooses the regions to evaluate.

### Japan West example: 25 VMs across 10 candidate SKUs

For `POST /api/scores/{region}`, select the example
**Japan West: 25 VMs, 10 SKUs (legacy versions only)**.
Manually set `region=japanwest`, `api-version=2026-09-05-preview`, and
`refresh=false`. Selecting a Swagger example only fills the JSON body; it
does not set path or query parameters.

The request evaluates **25 instances per zone for each candidate SKU**; it does
not divide 25 instances among the 10 SKUs or deploy any VMs. The 10-size request
fits the legacy 20-size limit but will be rejected locally with HTTP 400 under
`2026-10-05-preview`, which allows at most three sizes.

Equivalent Swagger-generated cURL (Bash syntax; run in Git Bash or WSL, not
directly in PowerShell):

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/api/scores/japanwest?api-version=2026-09-05-preview&refresh=false' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "desiredLocations": [
    "japanwest"
  ],
  "desiredSizes": [
    {"sku": "Standard_L32s_v3"},
    {"sku": "Standard_L32as_v3"},
    {"sku": "Standard_L32s_v4"},
    {"sku": "Standard_L32as_v4"},
    {"sku": "Standard_L32aos_v4"},
    {"sku": "Standard_L32als_v4"},
    {"sku": "Standard_L32s_v2"},
    {"sku": "Standard_E32ds_v5"},
    {"sku": "Standard_E32ads_v5"},
    {"sku": "Standard_E32bds_v5"}
  ],
  "desiredCount": 25,
  "availabilityZones": true
}'
```

Actual SKU support, zone availability, quota, and scores are determined by
Azure. This example is not a recorded successful live result. Execute only
when authorized and within your subscription's call allowance.

### What counts as a successful test?

HTTP 200 with a contract-valid response demonstrates a successful API call.
It does **not** require a `High` score. A restricted SKU, quota shortage, or
stale data can be a valid result. Do not deploy resources merely to validate
this harness.

| Score | Interpretation |
|---|---|
| `High`, `Medium`, `Low` | Relative likelihood of allocation, not an allocation guarantee |
| `InsufficientQuota` | Current-preview quota shortage for the requested allocation |
| `RestrictedSkuNotAvailable` | SKU is unavailable for this subscription in the returned scope |
| `DataNotFoundOrStale` | Capacity data is unavailable or stale |

`placementPreference` is 0-10, higher is better, and should only be used to
break ties within the same score tier in **one response**. Do not compare it
across separate requests. An absent legacy `isQuotaAvailable` value means quota
information was unavailable, not that quota is sufficient.

## 4. Verify caching without another scoring call

Immediately execute the **identical** successful request again with
`refresh=false`.

Expected:

- HTTP 200 and a body identical to the first response.
- `x-poc-cache: HIT`.
- `x-poc-cache-ttl-seconds` between 0 and 900.
- No additional Azure scoring call for the repeat request.

The initial request is normally `MISS`, unless already cached. Scope, URI
region, API version, and complete request payload affect the cache key.
Region/SKU ordering matters. Cache entries expire after 15 minutes; the cache
is bounded to 256 entries and resets on restart.

Do not enable `refresh=true` just to demonstrate caching: it deliberately
bypasses the cache and consumes another call. Errors are not cached, so
repeating a failed request calls Azure again unless local validation rejects it.

## 5. Exercise other scenarios selectively

Both POST operations offer an **Examples** dropdown in the request-body
section. Select an example, review and edit its JSON, and then execute.
The examples may request multiple regions/sizes: reduce them if you only need
a minimal test. Do not run every scenario against a tightly rate-limited service.

| Scenario / example | Action | Expected evidence or caveat |
|---|---|---|
| Regional / `regional` | Set `availabilityZones=false` | Regional results; zone field may be omitted |
| Zonal / `zonal` | Set `availabilityZones=true` | Zone-scoped results in zone-enabled regions; do not assume every region has zones |
| URI-region default / `uri-region` | Omit `desiredLocations` with the current preview | Response defaults locations to the URI region; legacy versions reject omission |
| Resource-group scope | Use `POST /api/resource-groups/{resource_group}/scores/{region}` with an existing group | Request succeeds if scope, permissions and preview access permit; no group is created |
| Storage / `storage` | Supply OS disk and optional data disk types | Check whether `storageProfile` is echoed; a 200 without an echo does not verify storage-aware scoring |
| VMSS / `vmss` | Use uniform orchestration with single placement group and fault-domain count | Options are passed to Azure; service-specific constraints remain Azure-authoritative |
| Flow mapping / `flow` | Enable `enableFlowVmSizes` | Requested sizes remain echoed unchanged; fallback to original sizes is allowed, so a 200 does not prove mapping occurred |
| Flex mapping / `flex` | Supply an actual mapped flex SKU and enable `mapFlexToStandardSizes` | Mapping depends on service data; never enable both mapping flags |
| Tags / `tags-policy` | Supply string tags and a supported zone policy | Options are accepted/echoed as supported; policy casing is canonicalized locally |
| ODCR / `odcr` | Replace the all-zero subscription, group and reservation placeholders with a real existing capacity reservation group ID | Azure validates pool access/existence; this harness does not create reservations |

Storage scoring requires separate caller and region onboarding. Merely sending
a storage payload is not proof that Azure used it in the scoring decision.
Physical-zone display, subscription-check bypass and the internal S2S endpoint
are intentionally not available in this public ARM harness.

## 6. Check local validation safely

These requests should return HTTP 400 **before any Azure call**. Start from the
minimal body and make one change at a time. Restore a valid body afterward.

| Invalid change | Expected local rejection |
|---|---|
| `desiredCount: 0` | Count below minimum |
| `desiredCount: 101` with current preview | Current-preview maximum exceeded |
| Empty `desiredSizes` | At least one size required |
| Four sizes with current preview | Current-preview size limit exceeded |
| Omit `desiredLocations` with a legacy version | Legacy locations required |
| Set both mapping flags to `true` | Mutually exclusive options |
| Set `vmssSinglePlacementGroup=true` without uniform mode | Invalid VMSS option combination |
| Supply `storageProfile: {}` | Required OS disk configuration missing |
| Supply an unsupported disk type or more than 10 data disks | Invalid storage configuration |
| Supply `vmTags: {"": "value"}` or `{"workload": null}` | Invalid tag key/value |
| Use `"true"` instead of `true` for a boolean | Wrong JSON type |

Local errors use an ARM-style `error` object. Schema errors include validation
details; cross-field/version errors describe the failed constraint.
Use the offline tests for broader invalid-input coverage rather than attempting
to provoke Azure errors:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 7. Troubleshoot actual server responses

| Symptom | Action |
|---|---|
| Startup says `Set AZURE_SUBSCRIPTION_ID...` | Set a valid GUID in the server terminal and restart |
| Browser cannot connect | Check server terminal, host/port, and `/health` |
| Swagger is blank but `/health` works | Swagger assets use external CDNs; check browser/network policy and `/openapi.json` |
| 400 `NoRegisteredProviderFound` | Inspect `/api/provider`; select an advertised version and region |
| 400 local validation error | Fix the body/parameters; no Azure call was made |
| 400 other Azure validation error | Read Azure's returned code/message; SKU families and allocation constraints are service-validated |
| 401 `LocalAzureAuthenticationFailed` | Run `az login` in the relevant environment and verify access to the configured subscription |
| 401 from Azure | Inspect the returned error and refresh the CLI sign-in as needed |
| 403 | Check caller RBAC and preview access/allow-list; this harness does not grant either |
| 429 | Stop scoring calls and honor `Retry-After`, if supplied; no automatic retry occurs |
| 500/503 from Azure | Record request IDs and the error; avoid repeated live retries |
| 502 `UpstreamContractMismatch` | Inspect `upstreamResponse` and confirm the selected contract; do not treat it as a valid score |
| 502 connection/non-JSON error or 504 timeout | Check network/proxy/service availability; an upstream timeout may still have consumed a call |
| 200 but missing storage echo | Storage-aware scoring is not verified for this request/caller |
| 200 `RestrictedSkuNotAvailable` | Valid API response; consider another authorized SKU/region only if call allowance permits |

Azure request IDs, correlation IDs, selected rate-limit headers and `Retry-After`
are preserved when supplied. A cache hit retains the original Azure request IDs;
it does not indicate a new upstream request.

## 8. Record a test result

For an authorized local test record, capture:

- Date/time, scope, region, version and sanitized request.
- HTTP status and whether the result was a cache hit.
- Score values, quota-field behavior and storage echo presence.
- Azure request ID for troubleshooting.
- Outcome: passed, failed, or blocked by access/version/onboarding prerequisites.

Do not commit subscription IDs, tokens, resource IDs, screenshots with account
details, or raw live responses. Existing `live-results.json` and
`live-*-results.json` patterns are ignored, but arbitrary evidence filenames are
not automatically protected.

For a repeatable live check without manual Swagger interaction, see the
[live smoke runner instructions](README.md#verification). The runner is opt-in
and also consumes Azure calls.
