"""Double-click launcher; keeps the local app available without a console window."""
import os
from pathlib import Path
import sys
import urllib.request
import json
import webbrowser

import prototype

root = Path(__file__).resolve().parent.parent
for port in range(8787, 8798):
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(url + "/api/bootstrap", timeout=1) as response:
            value = json.load(response)
        if value.get("application") == "cadbridge-local-prototype":
            webbrowser.open(url + "/workspace")
            sys.exit(0)
    except Exception:
        pass
    try:
        prototype.serve(port, open_browser=True)
        break
    except OSError:
        continue
