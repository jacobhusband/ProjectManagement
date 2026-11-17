"""Prepare the public desktop configuration without bundling personal keys."""

import sys
from pathlib import Path

from dotenv import dotenv_values


PUBLIC_CONFIG_KEYS = (
    "MICROSOFT_OAUTH_CLIENT_ID",
    "MICROSOFT_OAUTH_TENANT_ID",
)


def write_distribution_env(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("Distribution configuration must not overwrite the source .env")
    values = dotenv_values(source, interpolate=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in PUBLIC_CONFIG_KEYS:
        if values.get(key):
            escaped = values[key].replace("\\", "\\\\").replace("'", "\\'")
            lines.append(f"{key}='{escaped}'\n")
    destination.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    write_distribution_env(*sys.argv[1:])
