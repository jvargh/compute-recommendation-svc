import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient

import app as app_module
from app import app, get_service
from examples import EXAMPLES
from models import CURRENT_VERSION, PlacementRequest
from service import CACHE_TTL, SUBSCRIPTION, PlacementService

CURRENT = {"api-version": CURRENT_VERSION}
LEGACY = {"api-version": "2026-09-05-preview"}
BODY = {
    "desiredLocations": ["eastus"],
    "desiredSizes": [{"sku": "Standard_D2_v2"}],
    "desiredCount": 1,
    "availabilityZones": True,
}


class FakeCredential:
    def __init__(self):
        self.calls = 0

    def get_token(self, *scopes):
        self.calls += 1
        assert scopes == ("https://management.azure.com/.default",)
        return AccessToken("test-token-not-a-secret", int(time.time()) + 3600)


def success(request):
    payload = json.loads(request.content)
    current = request.url.params["api-version"] == CURRENT_VERSION
    score = {"sku": "Standard_D2_v2", "region": "eastus", "score": "High"}
    score["placementPreference" if current else "isQuotaAvailable"] = 9 if current else True
    return httpx.Response(200, json={
        "desiredLocations": payload.get("desiredLocations") or ["eastus"],
        "desiredSizes": payload["desiredSizes"],
        "desiredCount": payload.get("desiredCount", 1),
        "availabilityZones": payload.get("availabilityZones", False),
        "additionalProperties": payload.get("additionalProperties", {}),
        **({"storageProfile": payload["storageProfile"]} if "storageProfile" in payload else {}),
        "placementScores": [score],
    }, headers={"x-ms-request-id": "azure-request-id"})


@pytest.fixture
def harness():
    calls = []
    state = {"handler": success, "now": 0.0}
    credential = FakeCredential()

    def handler(request):
        calls.append(request)
        return state["handler"](request)

    service = PlacementService(
        credential, httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: state["now"],
    )
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        yield client, service, calls, state
    app.dependency_overrides.clear()
    service.close()


def post(client, body=None, params=None, route="/api/scores/eastus"):
    return client.post(route, json=BODY if body is None else body, params=params or CURRENT)


def test_current_and_legacy_contracts_and_no_fallback(harness):
    client, _, calls, _ = harness
    current = post(client).json()["placementScores"][0]
    legacy = post(client, params=LEGACY).json()["placementScores"][0]
    assert current["placementPreference"] == 9
    assert "isQuotaAvailable" not in current
    assert legacy["isQuotaAvailable"] is True
    assert "placementPreference" not in legacy
    assert [r.url.params["api-version"] for r in calls] == [
        CURRENT_VERSION, "2026-09-05-preview",
    ]


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_public_example_is_callable(harness, name):
    client, _, calls, _ = harness
    result = post(client, EXAMPLES[name]["value"])
    assert result.status_code == 200, result.text
    assert json.loads(calls[0].content) == EXAMPLES[name]["value"]


@pytest.mark.parametrize("version", [
    "2026-09-05-preview", "2026-05-05-preview", "2025-06-05",
    "2025-06-05-preview", "2025-02-01-preview", "2024-06-01-preview",
])
def test_supported_legacy_versions(harness, version):
    client, _, calls, _ = harness
    assert post(client, params={"api-version": version}).status_code == 200
    assert calls[0].url.params["api-version"] == version


def test_resource_group_scope_and_auth_header(harness):
    client, _, calls, _ = harness
    result = post(client, route="/api/resource-groups/existing-rg/scores/eastus")
    assert result.status_code == 200
    assert calls[0].url.path == (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/existing-rg"
        "/providers/Microsoft.Compute/locations/eastus/placementScores/regular/generate"
    )
    assert calls[0].headers["authorization"] == "Bearer test-token-not-a-secret"
    assert calls[0].headers["x-ms-client-request-id"]
    assert "test-token" not in result.text


@pytest.mark.parametrize("locations", [None, []])
def test_current_optional_locations_preserves_input(harness, locations):
    client, _, calls, _ = harness
    body = {"desiredSizes": BODY["desiredSizes"]}
    if locations is not None:
        body["desiredLocations"] = locations
    assert post(client, body).status_code == 200
    assert json.loads(calls[0].content) == body
    assert post(client, body, LEGACY).status_code == 400
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [
    ("desiredSizes", []),
    ("desiredSizes", [{"sku": "X"}] * 4),
    ("desiredCount", 0), ("desiredCount", 101), ("desiredCount", True),
    ("desiredCount", "10"), ("availabilityZones", "true"),
    ("desiredLocations", ["eastus"] * 6),
    ("desiredLocations", ["../westus"]), ("desiredLocations", None),
    ("desiredSizes", [{"sku": ""}]), ("desiredSizes", [{"sku": "   "}]),
    ("unexpected", True),
])
def test_invalid_current_inputs_do_not_call_azure(harness, field, value):
    client, _, calls, _ = harness
    result = post(client, {**BODY, field: value})
    assert result.status_code == 400
    assert "error" in result.json()
    assert calls == []


@pytest.mark.parametrize("field,value", [
    ("desiredCount", 100), ("desiredSizes", [{"sku": "X"}] * 3),
    ("desiredLocations", ["eastus"] * 5),
])
def test_current_exact_upper_bounds(harness, field, value):
    client, _, _, _ = harness
    assert post(client, {**BODY, field: value}).status_code == 200


def test_legacy_exact_limits(harness):
    client, _, calls, _ = harness
    body = {**BODY, "desiredCount": 1000, "desiredSizes": [{"sku": "X"}] * 20}
    assert post(client, body, LEGACY).status_code == 200
    for changed in (
        {**body, "desiredCount": 1001},
        {**body, "desiredSizes": [{"sku": "X"}] * 21},
    ):
        assert post(client, changed, LEGACY).status_code == 400
    assert len(calls) == 1


@pytest.mark.parametrize("properties", [
    {"vmssSinglePlacementGroup": True},
    {"mapFlexToStandardSizes": True, "enableFlowVmSizes": True},
    {"zonePlacementPolicy": "invalid"},
    {"vmTags": {"": "value"}}, {"vmTags": {"a": None}},
    {"vmTags": {"a": 42}}, {"vmTags": {" ": "value"}},
    {"displayInPhysicalZones": True}, {"BypassSubscriptionChecks": "Quota"},
    {"vmssOrchestrationMode": "invalid"}, {"ultraSSDEnabled": "false"},
])
def test_invalid_or_internal_options(harness, properties):
    client, _, calls, _ = harness
    assert post(client, {**BODY, "additionalProperties": properties}).status_code == 400
    assert calls == []


@pytest.mark.parametrize("policy", ["any", "AUTO", "platformbesteffortalignment"])
def test_zone_policy_case_insensitive(harness, policy):
    client, _, calls, _ = harness
    assert post(client, {**BODY, "additionalProperties": {"zonePlacementPolicy": policy}}).status_code == 200
    assert json.loads(calls[0].content)["additionalProperties"]["zonePlacementPolicy"] in (
        "Any", "Auto", "PlatformBestEffortAlignment",
    )


@pytest.mark.parametrize("profile", [
    {}, {"osDisk": {}}, {"osDisk": {"managedDisk": {}}},
    {"osDisk": {"managedDisk": {"storageAccountType": "BAD"}}},
    {"osDisk": {"managedDisk": {"storageAccountType": ""}}},
    {"osDisk": {"managedDisk": {"storageAccountType": None}}},
    {"osDisk": {"managedDisk": {"storageAccountType": "Premium_LRS"}},
     "dataDisks": [{"managedDisk": {"storageAccountType": "BAD"}}]},
    {"osDisk": {"managedDisk": {"storageAccountType": "Premium_LRS"}}, "dataDisks": [{}] * 11},
])
def test_invalid_storage(harness, profile):
    client, _, calls, _ = harness
    assert post(client, {**BODY, "storageProfile": profile}).status_code == 400
    assert calls == []


def test_storage_case_preservation_skipped_disks_and_exact_max(harness):
    client, _, calls, _ = harness
    storage = {
        "osDisk": {"managedDisk": {"storageAccountType": "pReMiUm_LrS"}},
        "dataDisks": [{}, {"managedDisk": {}}, {"managedDisk": {"storageAccountType": ""}}] + [{}] * 7,
    }
    result = post(client, {**BODY, "storageProfile": storage})
    assert result.status_code == 200
    assert json.loads(calls[0].content)["storageProfile"] == storage
    assert result.json()["storageProfile"] == storage


def test_storage_omitted_by_unonboarded_upstream_is_not_fabricated(harness):
    client, _, _, state = harness

    def no_storage(request):
        result = success(request).json()
        result.pop("storageProfile", None)
        return httpx.Response(200, json=result)

    state["handler"] = no_storage
    result = post(client, EXAMPLES["storage"]["value"])
    assert result.status_code == 200
    assert "storageProfile" not in result.json()


def test_cache_exact_ttl_refresh_and_credential_reuse(harness):
    client, service, calls, state = harness
    first = post(client)
    assert first.headers["x-poc-cache"] == "MISS"
    state["now"] = CACHE_TTL - 1
    second = post(client)
    assert second.headers["x-poc-cache"] == "HIT"
    assert second.headers["x-poc-cache-ttl-seconds"] == "1"
    assert first.json() == second.json()
    state["now"] = CACHE_TTL
    assert post(client).headers["x-poc-cache"] == "MISS"
    assert post(client, params={**CURRENT, "refresh": True}).headers["x-poc-cache"] == "MISS"
    assert len(calls) == 3
    assert service.credential.calls == 1


def test_cache_scope_version_options_and_order_are_distinct(harness):
    client, _, calls, _ = harness
    post(client)
    post(client, params=LEGACY)
    post(client, route="/api/resource-groups/rg/scores/eastus")
    post(client, {**BODY, "availabilityZones": False})
    post(client, {**BODY, "desiredLocations": ["eastus", "westus"]})
    post(client, {**BODY, "desiredLocations": ["westus", "eastus"]})
    post(client, dict(reversed(list(BODY.items()))))
    assert len(calls) == 6


def test_cache_bounded(harness):
    _, service, _, _ = harness
    for number in range(260):
        body = PlacementRequest.model_validate({
            **BODY, "additionalProperties": {"vmTags": {"test": str(number)}},
        })
        assert service.generate(body, "eastus", CURRENT_VERSION).status == 200
    assert len(service.cache) == 256


def test_concurrent_requests_share_one_upstream_call(harness):
    _, service, calls, _ = harness
    body = PlacementRequest.model_validate(BODY)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.generate(body, "eastus", CURRENT_VERSION), range(8)))
    assert all(result.status == 200 for result in results)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_azure_errors_preserved_not_cached_or_retried(harness, status):
    client, _, calls, state = harness
    error = {"error": {"code": "AzureSpecificError", "message": "Test upstream error"}}
    state["handler"] = lambda _: httpx.Response(
        status, json=error, headers={"retry-after": "120", "x-ms-request-id": "id"},
    )
    first = post(client)
    assert first.status_code == status
    assert first.json() == error
    assert first.headers["retry-after"] == "120"
    assert first.headers["x-ms-request-id"] == "id"
    assert len(calls) == 1
    assert post(client).status_code == status
    assert len(calls) == 2


def test_unsupported_version_never_falls_back(harness):
    client, _, calls, state = harness
    state["handler"] = lambda _: httpx.Response(
        400, json={"error": {"code": "NoRegisteredProviderFound", "message": "Not deployed"}},
    )
    assert post(client).status_code == 400
    assert len(calls) == 1
    assert calls[0].url.params["api-version"] == CURRENT_VERSION


def test_local_auth_failure(harness):
    client, service, calls, _ = harness

    class FailedCredential:
        def get_token(self, *scopes):
            raise ClientAuthenticationError(message="Do not expose sensitive auth diagnostics")

    service.credential = FailedCredential()
    result = post(client)
    assert result.status_code == 401
    assert result.json()["error"]["code"] == "LocalAzureAuthenticationFailed"
    assert "sensitive" not in result.text
    assert calls == []


@pytest.mark.parametrize("exception,status", [
    (httpx.ReadTimeout("timeout"), 504),
    (httpx.ConnectError("network"), 502),
])
def test_transport_errors(harness, exception, status):
    client, _, calls, state = harness

    def fail(_):
        raise exception

    state["handler"] = fail
    assert post(client).status_code == status
    assert len(calls) == 1


@pytest.mark.parametrize("status,expected", [(200, 502), (403, 403)])
def test_non_json(harness, status, expected):
    client, _, _, state = harness
    state["handler"] = lambda _: httpx.Response(status, text="<html>upstream error</html>")
    result = post(client)
    assert result.status_code == expected
    assert result.json()["error"]["code"] == "AzureNonJsonResponse"


@pytest.mark.parametrize("score", [
    {"score": "Other", "placementPreference": 5},
    {"score": "High"}, {"score": "High", "placementPreference": 11},
    {"score": "High", "placementPreference": 5, "isQuotaAvailable": True},
])
def test_current_response_contract_mismatch_is_explicit(harness, score):
    client, _, _, state = harness

    def invalid_response(request):
        body = success(request).json()
        body["placementScores"][0] = {"sku": "X", "region": "eastus", **score}
        return httpx.Response(200, json=body)

    state["handler"] = invalid_response
    result = post(client)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "UpstreamContractMismatch"
    assert "upstreamResponse" in result.json()


@pytest.mark.parametrize("score", [
    "High", "Medium", "Low", "InsufficientQuota",
    "RestrictedSkuNotAvailable", "DataNotFoundOrStale",
])
def test_all_current_score_values(harness, score):
    client, _, _, state = harness

    def response(request):
        body = success(request).json()
        body["placementScores"][0]["score"] = score
        return httpx.Response(200, json=body)

    state["handler"] = response
    assert post(client).status_code == 200
    assert post(client).json()["placementScores"][0]["score"] == score


def test_legacy_quota_unavailable_can_be_omitted(harness):
    client, _, _, state = harness

    def no_quota(request):
        body = success(request).json()
        body["placementScores"][0].pop("isQuotaAvailable")
        return httpx.Response(200, json=body)

    state["handler"] = no_quota
    assert post(client, params=LEGACY).status_code == 200
    assert "isQuotaAvailable" not in post(client, params=LEGACY).json()["placementScores"][0]


def test_diagnostics_use_fixed_read_only_endpoints(harness):
    client, _, calls, state = harness
    state["handler"] = lambda _: httpx.Response(200, json={"properties": {"state": "Registered"}})
    assert client.get("/api/provider").status_code == 200
    assert client.get("/api/features/ComputePlacementScores").status_code == 200
    assert client.get("/api/features/ComputePlacementScoresGA").status_code == 200
    assert all(request.method == "GET" for request in calls)
    assert all(f"/subscriptions/{SUBSCRIPTION}/" in request.url.path for request in calls)
    assert client.get("/api/features/OtherFeature").status_code == 400
    assert len(calls) == 3


def test_docs_schema_health_and_config_need_no_azure_calls(harness):
    client, _, calls, _ = harness
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/config").json()["subscriptionId"] == SUBSCRIPTION
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/scores/{region}"]["post"]
    assert set(operation["requestBody"]["content"]["application/json"]["examples"]) == set(EXAMPLES)
    properties = schema["components"]["schemas"]["AdditionalProperties"]["properties"]
    assert set(properties) == {
        "vmssOrchestrationMode", "vmssSinglePlacementGroup", "vmssPlatformFaultDomainCount",
        "additionalCapacityPools", "ultraSSDEnabled", "zonePlacementPolicy",
        "vmTags", "mapFlexToStandardSizes", "enableFlowVmSizes",
    }
    assert calls == []


def test_invalid_uri_version_and_missing_size(harness):
    client, _, calls, _ = harness
    assert post(client, {}).status_code == 400
    assert post(client, params={"api-version": "bad"}).status_code == 400
    assert post(client, route="/api/scores/East%20US").status_code == 400
    assert post(client, route="/api/resource-groups/bad!/scores/eastus").status_code == 400
    assert client.post("/api/scores/eastus", content="{bad").status_code == 400
    assert calls == []


def test_no_mutation_of_input(harness):
    client, _, _, _ = harness
    before = copy.deepcopy(BODY)
    assert post(client).status_code == 200
    assert BODY == before


@pytest.mark.parametrize("subscription", ["", "not-a-guid"])
def test_invalid_subscription_configuration_fails_startup(monkeypatch, subscription):
    monkeypatch.setattr(app_module, "SUBSCRIPTION", subscription)
    with pytest.raises(RuntimeError, match="Set AZURE_SUBSCRIPTION_ID"), TestClient(app):
        pass
