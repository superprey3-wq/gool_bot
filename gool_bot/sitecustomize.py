import os

# GitHub-hosted runners can receive an empty/anti-bot event listing from the
# default OddsPortal domain. OddsHarvester officially supports regional base
# URLs, so use one by default while still allowing an explicit override.
os.environ.setdefault("OH_BASE_URL", "https://www.centroquote.it")
