from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURRENT_VERSION = "2026-10-05-preview"
ApiVersion = Literal[
    "2026-10-05-preview",
    "2026-09-05-preview",
    "2026-05-05-preview",
    "2025-06-05",
    "2025-06-05-preview",
    "2025-02-01-preview",
    "2024-06-01-preview",
]
Region = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]{0,62}$")]
NonEmpty = Annotated[str, Field(min_length=1, pattern=r"\S")]
Score = Literal[
    "High", "Medium", "Low", "InsufficientQuota",
    "RestrictedSkuNotAvailable", "DataNotFoundOrStale",
]
DISK_TYPES = {
    "standard_lrs", "standardssd_lrs", "standardssd_zrs",
    "premium_lrs", "premium_zrs", "premiumv2_lrs", "ultrassd_lrs",
}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Size(RequestModel):
    sku: NonEmpty


class ManagedDisk(RequestModel):
    storageAccountType: str = Field(
        default="",
        description="Case-insensitive. Empty/omitted types are skipped on data disks only.",
        examples=["Premium_LRS"],
    )

    @field_validator("storageAccountType")
    @classmethod
    def supported_type(cls, value: str) -> str:
        if value and value.lower() not in DISK_TYPES:
            raise ValueError("Unsupported managed disk storageAccountType")
        return value


class OsDisk(RequestModel):
    managedDisk: ManagedDisk

    @model_validator(mode="after")
    def required_type(self) -> Self:
        if not self.managedDisk.storageAccountType:
            raise ValueError("OS disk storageAccountType is required and must be non-empty")
        return self


class DataDisk(RequestModel):
    managedDisk: ManagedDisk | None = None


class StorageProfile(RequestModel):
    osDisk: OsDisk
    dataDisks: list[DataDisk] = Field(default_factory=list, max_length=10)


class CapacityPools(RequestModel):
    capacityReservationGroup: Annotated[
        str,
        Field(
            pattern=(
                r"(?i)^/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+"
                r"/providers/Microsoft\.Compute/capacityReservationGroups/[^/]+$"
            )
        ),
    ]


class AdditionalProperties(RequestModel):
    vmssOrchestrationMode: Literal["flex", "uniform"] = "flex"
    vmssSinglePlacementGroup: bool = False
    vmssPlatformFaultDomainCount: int = 1
    additionalCapacityPools: CapacityPools | None = None
    ultraSSDEnabled: bool = False
    zonePlacementPolicy: Literal["Any", "PlatformBestEffortAlignment", "Auto"] | None = None
    vmTags: dict[NonEmpty, str] = Field(default_factory=dict)
    mapFlexToStandardSizes: bool | None = None
    enableFlowVmSizes: bool | None = None

    @field_validator("zonePlacementPolicy", mode="before")
    @classmethod
    def canonical_policy(cls, value: object) -> object:
        if isinstance(value, str):
            for policy in ("Any", "PlatformBestEffortAlignment", "Auto"):
                if policy.lower() == value.lower():
                    return policy
        return value

    @model_validator(mode="after")
    def compatible_options(self) -> Self:
        if self.vmssSinglePlacementGroup and self.vmssOrchestrationMode != "uniform":
            raise ValueError("vmssSinglePlacementGroup requires uniform orchestration")
        if self.mapFlexToStandardSizes and self.enableFlowVmSizes:
            raise ValueError("mapFlexToStandardSizes and enableFlowVmSizes are mutually exclusive")
        return self


class PlacementRequest(RequestModel):
    desiredLocations: list[Region] = Field(
        default_factory=list, max_length=5,
        description="Current preview: omitted/empty defaults to URI region. Legacy: required.",
    )
    desiredSizes: list[Size] = Field(min_length=1, max_length=20)
    desiredCount: int = Field(default=1, ge=1, le=1000)
    availabilityZones: bool = False
    storageProfile: StorageProfile | None = None
    additionalProperties: AdditionalProperties | None = None

    def check_version(self, version: str) -> None:
        if version == CURRENT_VERSION:
            if len(self.desiredSizes) > 3 or self.desiredCount > 100:
                raise ValueError("Current preview permits at most 3 sizes and desiredCount <= 100")
        elif not self.desiredLocations:
            raise ValueError("Legacy versions require 1-5 desiredLocations")

    def payload(self) -> dict:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class PlacementScore(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    sku: str
    region: str
    availabilityZone: str | None = None
    score: Score
    placementPreference: Annotated[int, Field(ge=0, le=10)] | None = None
    isQuotaAvailable: bool | None = None


class PlacementResponse(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    desiredLocations: list[str]
    desiredSizes: list[Size]
    desiredCount: int
    availabilityZones: bool
    additionalProperties: dict | None = None
    storageProfile: dict | None = None
    placementScores: list[PlacementScore]

    def check_version(self, version: str) -> None:
        for score in self.placementScores:
            if version == CURRENT_VERSION:
                if score.placementPreference is None:
                    raise ValueError("Current preview must return placementPreference")
                if "isQuotaAvailable" in score.model_fields_set:
                    raise ValueError("Current preview must not return isQuotaAvailable")
            elif score.score == "InsufficientQuota":
                raise ValueError("Legacy versions must not return InsufficientQuota")
