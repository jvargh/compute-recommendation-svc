import os

# Tests always use a synthetic subscription, regardless of the developer's environment.
os.environ["AZURE_SUBSCRIPTION_ID"] = "00000000-0000-0000-0000-000000000001"
