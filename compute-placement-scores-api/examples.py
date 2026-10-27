BASE = {
    "desiredLocations": ["eastus", "westus"],
    "desiredSizes": [{"sku": "Standard_D2_v2"}, {"sku": "Standard_D8s_v3"}],
    "desiredCount": 1,
    "availabilityZones": True,
}

EXAMPLES = {
    "japanwest-25-vms-legacy": {
        "summary": "Japan West: 25 VMs, 10 SKUs (legacy versions only)",
        "description": (
            "Set region=japanwest, api-version=2026-09-05-preview and refresh=false. "
            "The 10 sizes exceed the current preview's 3-size limit. "
            "Swagger example selection fills only the body, not the parameters."
        ),
        "value": {
            "desiredLocations": ["japanwest"],
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
                {"sku": "Standard_E32bds_v5"},
            ],
            "desiredCount": 25,
            "availabilityZones": True,
        },
    },
    "zonal": {"summary": "Zonal scores across regions and sizes", "value": BASE},
    "regional": {
        "summary": "Regional scores",
        "value": {**BASE, "availabilityZones": False},
    },
    "uri-region": {
        "summary": "Default to URI region (current preview only)",
        "value": {"desiredSizes": [{"sku": "Standard_D2_v2"}]},
    },
    "storage": {
        "summary": "Storage-aware scoring (requires separate onboarding)",
        "value": {
            **BASE,
            "storageProfile": {
                "osDisk": {"managedDisk": {"storageAccountType": "Premium_LRS"}},
                "dataDisks": [
                    {"managedDisk": {"storageAccountType": "PremiumV2_LRS"}},
                    {"managedDisk": {"storageAccountType": "Premium_ZRS"}},
                ],
            },
            "additionalProperties": {"ultraSSDEnabled": False, "zonePlacementPolicy": "Any"},
        },
    },
    "vmss": {
        "summary": "Uniform VMSS, single placement group and fault domains",
        "value": {
            **BASE,
            "additionalProperties": {
                "vmssOrchestrationMode": "uniform",
                "vmssSinglePlacementGroup": True,
                "vmssPlatformFaultDomainCount": 1,
            },
        },
    },
    "flow": {
        "summary": "Flow VM size mapping",
        "value": {**BASE, "additionalProperties": {"enableFlowVmSizes": True}},
    },
    "flex": {
        "summary": "Flex-to-standard size mapping (replace SKU with a mapped flex SKU)",
        "value": {**BASE, "additionalProperties": {"mapFlexToStandardSizes": True}},
    },
    "tags-policy": {
        "summary": "VM tags and automatic zone placement",
        "value": {
            **BASE,
            "additionalProperties": {
                "zonePlacementPolicy": "Auto",
                "vmTags": {"workload": "placement-score-poc"},
            },
        },
    },
    "odcr": {
        "summary": "Capacity reservation pool (replace resource ID with an existing group)",
        "value": {
            **BASE,
            "additionalProperties": {
                "additionalCapacityPools": {
                    "capacityReservationGroup": (
                        "/subscriptions/00000000-0000-0000-0000-000000000000"
                        "/resourceGroups/REPLACE-ME/providers/Microsoft.Compute"
                        "/capacityReservationGroups/REPLACE-ME"
                    )
                }
            },
        },
    },
}
