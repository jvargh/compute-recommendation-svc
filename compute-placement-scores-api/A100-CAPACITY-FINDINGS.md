# A100 placement-score investigation

Report date: **30 October 2026**. Times below are **EDT (UTC-4)** unless noted.

**Historical observations, not current capacity commitments.** This report
summarizes previously executed Azure API checks; generating the report did not
issue new scoring calls. Refresh the scores before making a deployment decision.

## Summary

- The latest recorded US-only scan completed at **09:24:49 on 30 October**.
- For **one VM per zone**, `Standard_NC24ads_A100_v4` returned **High** in
  **West US 3, logical zone 2**. No other US candidate returned High or Medium.
- East US 2 returned **Low** for the three NC A100 sizes in zones 1 and 3.
- **Every result in the latest US scan returned `isQuotaAvailable=false`.**
  Favorable capacity signals therefore did not establish deployability.
- All checks used an accessible **test subscription**, not the intended
  production subscription. Production-subscription access was unavailable.
- No VMs, reservations, role assignments, or quota changes were created.

Subscription IDs, customer details, raw response bodies and request IDs are
intentionally excluded from this public report.

## Scope and method

The local FastAPI harness forwarded requests to the public ARM placement API:

```text
POST /subscriptions/{subscriptionId}/providers/Microsoft.Compute/locations/eastus2/placementScores/regular/generate?api-version=2026-09-05-preview
```

The URI region identifies the endpoint; `desiredLocations` identifies the
regions being scored. Requests used:

- Explicit legacy API version `2026-09-05-preview`.
- `availabilityZones=true`.
- `desiredCount=1`, except the initial East US 2 tests at counts 2 and 4.
- Up to five regions per request, with all candidate sizes in each batch.
- Fresh calls for the latest US scan, not cached results.

The current specification version, `2026-10-05-preview`, was previously
rejected by Azure as unavailable for the endpoint. There was no automatic
version fallback. The selected legacy contract returns quota separately from
the placement score and permits up to 20 sizes; the current contract permits
only three sizes.

### A100 SKU coverage

| Full SKU | Table label |
|---|---|
| `Standard_NC24ads_A100_v4` | NC24 |
| `Standard_NC48ads_A100_v4` | NC48 |
| `Standard_NC96ads_A100_v4` | NC96 |
| `Standard_ND96asr_v4` | ND96asr |
| `Standard_ND96amsr_A100_v4` | ND96amsr |

The initial catalog query matched names containing `A100` and found four
sizes. It was subsequently expanded to include `Standard_ND96asr_v4`, whose
name omits `A100`. A name-only search is therefore not sufficient to discover
all A100-powered families.

All five identified sizes have v4 names. This is the Azure VM-series
generation, not a GPU or MIG version. This investigation did not identify an
A100 v5/v6 offering and is not a guarantee of future catalog completeness.
Different VM sizes contain different GPU counts and memory configurations:
**one VM is not necessarily one physical GPU**.

## Latest US-only results

**30 October 2026, 09:24:22-09:24:49.** Both five-region/four-region batches
returned HTTP 200. Coverage includes all nine standard US public-cloud regions;
Government and EUAP regions were not included.

Legend:

- **H**: High allocation likelihood.
- **L**: Low allocation likelihood.
- **R**: `RestrictedSkuNotAvailable`.
- **D**: `DataNotFoundOrStale`.
- Numbers are returned **logical availability zones**.
- `regional` means Azure returned no availability-zone value.
- No Medium scores were returned.

| Region | NC24 | NC48 | NC96 | ND96asr | ND96amsr |
|---|---|---|---|---|---|
| Central US | L: 1,3; R: 2 | L: 1,3; R: 2 | L: 1,3; R: 2 | R: 1,2,3 | R: 1,2,3 |
| East US | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 |
| East US 2 | L: 1,3; R: 2,4 | L: 1,3; R: 2,4 | L: 1,3; R: 2,4 | R: 1,2,3,4 | L: 1,3; R: 2,4 |
| North Central US | R: regional | R: regional | R: regional | R: regional | R: regional |
| South Central US | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | L: 1; R: 2,3 |
| West Central US | R: regional | R: regional | R: regional | R: regional | R: regional |
| West US | R: regional | R: regional | R: regional | R: regional | R: regional |
| West US 2 | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | R: 1,2,3 | D: 2; R: 1,3 |
| West US 3 | **H: 2**; L: 1; R: 3 | L: 1,2; R: 3 | L: 1,2; R: 3 | R: 1,2,3 | R: 1,2,3 |

**Quota availability was false for every entry.** Zone labels, including the
zone 4 returned for East US 2, are reproduced from the API, not inferred from
another subscription's topology.

### Why earlier answers differed

For NC24 in West US 3 zone 2, the recorded observations were:

| Check | Result | Requested count per zone |
|---|---|---|
| Initial global scan, 29 October, started about 23:00 | High | 1 |
| Targeted fresh check, 30 October, 09:16 | Low | 1 |
| Latest US-only scan, 30 October, 09:24 | High | 1 |

These are separate point-in-time responses. They do not establish stable
capacity or guarantee that the same result will be returned later.

## Earlier global A100 work

### Initial four-SKU scan

The initial global scan evaluated four explicitly A100-named SKUs across
26 catalog-discovered, placement-API-supported regions in six successful
batches. It returned 284 score entries, including 20 High entries.

NC24 had High results in:

| Region | Logical zones |
|---|---|
| Brazil South | 3 |
| Canada Central | 1 |
| Central US | 3 |
| Germany West Central | 1,2 |
| Italy North | 2,3 |
| Poland Central | 1,3 |
| Southeast Asia | 3 |
| Sweden Central | 1,2 |
| Switzerland North | 1 |
| UK South | 2,3 |
| West Europe | 1 |
| West US 3 | 2 |

Other High results were NC48 in Italy North zone 2, and ND96amsr in Italy
North zone 2 and UK South zone 2. NC96 had no High result. All High entries
returned quota unavailable.

### Expanded five-SKU scan

A later worldwide scan added ND96asr and again evaluated 26 regions in six
successful batches. It returned **355 score entries**, of which **249** were
`RestrictedSkuNotAvailable`. The saved evidence records this scan on
30 October around **09:22**.

The 26 regions were Australia East, Brazil South, Canada Central, Canada East,
Central India, Central US, East US, East US 2, France Central, Germany West
Central, Italy North, Japan East, Jio India Central, Korea Central, North Europe,
Poland Central, South Central US, Southeast Asia, Sweden Central, Switzerland
North, UK South, UK West, West Europe, West US, West US 2, and West US 3.

Central US EUAP was catalog-listed but excluded because the placement API did
not advertise support. This was **not a scan of every Azure region**: it used
the union of discovered A100 catalog regions supported by the scoring endpoint.
The later US-only scan additionally checked North Central US and West Central US.

Restricted results were exported separately during analysis. A restricted
result indicates subscription/SKU/scope unavailability; it does not prove
that Azure has zero physical A100 capacity in that region.

## Earlier East US 2 production-feasibility investigation

On **29 October around 22:22**, fresh requests tested **2 and 4 VMs per zone**
for A100 and two non-confidential H100 alternatives. Both quantities returned
the same score patterns:

| SKU | Zone 1 | Zone 2 | Zone 3 | Zone 4 |
|---|---|---|---|---|
| `Standard_NC24ads_A100_v4` | Low | Restricted | Low | Restricted |
| `Standard_NC40ads_H100_v5` | High | Data unavailable/stale | Low | Restricted |
| `Standard_NC80adis_H100_v5` | Low | Data unavailable/stale | Low | Restricted |

Every result returned quota unavailable. Separate usage checks found zero
A100 and H100 family quota in the test subscription. These findings did not
confirm an initial 2-4 A100 VM production allocation.

The H100 result concerns **NCads**, not **NCCads**. The previously discussed
`Standard_NCC40ads_H100_v5` is a distinct confidential-GPU SKU and was not
covered by those H100 scoring calls. Its availability must be assessed separately.

## Interpretation and limitations

1. **High is not an allocation guarantee.** Low is not proof of zero capacity.
2. Scores are near-real-time signals, normally relevant for about 15-30 minutes,
   not sustained-production commitments or capacity reservations.
3. `isQuotaAvailable=false` blocks interpreting a favorable legacy score as
   currently deployable under the queried subscription.
4. Logical zones can map differently between subscriptions. Do not copy a
   zone number from the test subscription into a customer capacity commitment.
5. One-VM results do not confirm 2-4 VMs, larger pools, upgrade surge, replacement
   capacity, or simultaneous allocation across multiple candidates.
6. Tests used generic placement requests, not a validated AKS/VMSS storage and
   networking configuration. No workload performance was measured.
7. Production-subscription access was unavailable; none of these results is a
   production-subscription capacity confirmation.

## MIG and next steps

The objective was to investigate whether A100 MIG partitioning could reduce
the physical GPU-node requirement for an AKS-hosted workload.

- MIG partitions GPU resources, not independent hosts or failure domains.
- Do not assume 2-4 A100 VMs replace a requirement for five T4 nodes.
- Validate the exact application release, DU/CV workloads, GPU model, MIG
  profile, AKS configuration, concurrency, memory, throughput and node-loss recovery.
- AKS documents MIG support for A100, H100 and H200 series; exact SKU and
  configuration support still needs validation. V620 is not an NVIDIA MIG substitute.
- Confirm the actual production subscription, then rerun the chosen SKU,
  quantity and zones with authorized access.
- Obtain capacity-team confirmation of allocatable quantity, timing,
  replacement/scale-out headroom and any reservation requirements.
- Assess quota separately; this investigation did not request quota increases.
- If another region is acceptable, evaluate connectivity, latency, residency
  and cross-region transfer costs before choosing it.

References:

- [AKS multi-instance GPU documentation](https://learn.microsoft.com/en-us/azure/aks/gpu-multi-instance)
- [NCads H100 v5 documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncadsh100v5-series)
- [NCCads H100 v5 documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nccadsh100v5-series)
- [Swagger testing guide](SWAGGER-TESTING.md)

## Reproduce the US-only scan

Start the harness using the [setup instructions](README.md#run-on-windows).
The following PowerShell uses the **server's configured subscription**, not a
subscription selected in the shell running `Invoke-RestMethod`.

```powershell
$regions = @(
    'centralus', 'eastus', 'eastus2', 'northcentralus',
    'southcentralus', 'westcentralus', 'westus', 'westus2', 'westus3'
)
$sizes = @(
    @{ sku = 'Standard_NC24ads_A100_v4' }
    @{ sku = 'Standard_NC48ads_A100_v4' }
    @{ sku = 'Standard_NC96ads_A100_v4' }
    @{ sku = 'Standard_ND96asr_v4' }
    @{ sku = 'Standard_ND96amsr_A100_v4' }
)
$desiredCount = 1
$uri = 'http://127.0.0.1:8000/api/scores/eastus2?api-version=2026-09-05-preview&refresh=false'

$results = @(
    for ($i = 0; $i -lt $regions.Count; $i += 5) {
        $body = @{
            desiredLocations = @($regions | Select-Object -Skip $i -First 5)
            desiredSizes = $sizes
            desiredCount = $desiredCount
            availabilityZones = $true
        } | ConvertTo-Json -Depth 10

        $response = Invoke-RestMethod -Method Post -Uri $uri `
            -ContentType 'application/json' -Body $body -ErrorAction Stop
        $response.placementScores
    }
)

$results |
    Sort-Object region, sku, availabilityZone |
    Format-Table sku, region, availabilityZone, score, isQuotaAvailable -AutoSize
```

This prints **all scores**, not only restricted entries. It consumes up to
two scoring calls unless cached. Set `refresh=true` only when intentionally
requesting fresh scores; restarting the server also clears the in-memory cache.
Stop on throttling and honor `Retry-After`. No automatic retries occur.

For High/Medium/Low only:

```powershell
$results |
    Where-Object { $_.score -in @('High', 'Medium', 'Low') } |
    Format-Table sku, region, availabilityZone, score, isQuotaAvailable -AutoSize
```

Keep raw evidence and any identifying subscription/resource details local.
The report intentionally contains only sanitized historical summaries.
