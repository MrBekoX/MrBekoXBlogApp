#!/usr/bin/env python3
"""Generate Software Bill of Materials (SBOM)."""

import json
import subprocess
import sys
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any

def get_installed_packages() -> list:
    """Get installed packages via pip list."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error getting pip list: {e}")
        return []

def create_cyclonedx_sbom(packages: list) -> Dict[str, Any]:
    """Create a minimal CycloneDX 1.5 JSON SBOM."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "component": {
                "type": "application",
                "name": "blogapp-ai-agent",
                "version": "1.0.0"
            }
        },
        "components": []
    }

    for pkg in packages:
        component = {
            "type": "library",
            "name": pkg["name"],
            "version": pkg["version"],
            "purl": f"pkg:pypi/{pkg['name']}@{pkg['version']}"
        }
        bom["components"].append(component)

    return bom

def main():
    packages = get_installed_packages()
    if not packages:
        print("No packages found or pip failed.")
        sys.exit(1)

    bom = create_cyclonedx_sbom(packages)
    
    output_path = Path("sbom.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(bom, f, indent=2)

    print(f"SBOM generated at {output_path.absolute()}")
    print(f"Total components: {len(bom['components'])}")

if __name__ == "__main__":
    main()
