"""GOOL MonkeyBytes LIVE TOTAL O/U market runtime.

Uses the last validated HTTP collector core, but exposes an explicit Monkey
PROGRUZ build identity and applies the Flashscore project-id correction.
"""
from __future__ import annotations
from urllib.request import Request, urlopen

BUILD = "MONKEY-PROGRUZ-2026-08-29-B"
_VALIDATED = "https://raw.githubusercontent.com/superprey3-wq/gool_bot/4ac89fbd515c560d42e50bc6876f129421698bc4/browser_market_node.py"
print(f"GOOL MARKET BUILD {BUILD} core=validated-http", flush=True)
req = Request(_VALIDATED, headers={"User-Agent": "GOOL-Monkey-Progruz/2026.08.29"})
source = urlopen(req, timeout=20).read().decode("utf-8")
source = source.replace('"projectId": 5, "geoIpCode": "US"', '"projectId": 2, "geoIpCode": "US"')
# The old core called its diagnostics MARKET_V6. Rename only the diagnostic
# prefix so server logs identify the currently deployed Monkey PROGRUZ build.
source = source.replace("MARKET_V6", "MARKET_PROGRUZ")
source = source.replace("GOOL lightweight live market collector v6", "GOOL Monkey PROGRUZ validated HTTP collector core")
ns = globals()
original_name = ns.get("__name__", "browser_market_node")
ns["__name__"] = "browser_market_node_validated"
exec(compile(source, _VALIDATED, "exec"), ns, ns)
ns["__name__"] = original_name
if original_name == "__main__":
    main()
