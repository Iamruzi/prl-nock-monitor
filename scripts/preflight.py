#!/usr/bin/env python3
"""Offline runtime/configuration checks; no credentials needed."""
import json
from pathlib import Path
import ssl
import sys
from collect import load_config, source_specs

root = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ required; production uses Python 3.12")
ssl.create_default_context()
config = load_config()
assert len(source_specs(config)) == 6
assert config["prl_min_payout"] > 0 and config["nock_min_payout"] > 0
assert config["stale_after_seconds"] >= 300
for filename in ("index.html", "styles.css", "app.js"):
    assert (root / "site" / filename).is_file(), f"Missing {filename}"
print(json.dumps({"preflight": "ok", "python": sys.version.split()[0], "pip_dependencies": 0}))
