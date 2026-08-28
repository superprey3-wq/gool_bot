"""GOOL Flashscore/LSApp market collector loader.

Loads the last validated v6 collector source and applies the Flashscore global
project-id correction before executing it. This keeps the production collector
stable while aligning LSApp with the /2/ Flashscore feed.
"""
from __future__ import annotations
from urllib.request import Request,urlopen

_VALIDATED="https://raw.githubusercontent.com/superprey3-wq/gool_bot/4ac89fbd515c560d42e50bc6876f129421698bc4/browser_market_node.py"
req=Request(_VALIDATED,headers={"User-Agent":"GOOL-market-node/6"})
source=urlopen(req,timeout=20).read().decode("utf-8")
source=source.replace('"projectId": 5, "geoIpCode": "US"','"projectId": 2, "geoIpCode": "US"')
# Prevent the fetched module's __main__ guard from running during exec; the
# wrapper exposes all collector functions/globals and invokes main only below.
ns=globals();original_name=ns.get("__name__","browser_market_node");ns["__name__"]="browser_market_node_validated"
exec(compile(source,_VALIDATED,"exec"),ns,ns)
ns["__name__"]=original_name
if original_name=="__main__":
    main()
