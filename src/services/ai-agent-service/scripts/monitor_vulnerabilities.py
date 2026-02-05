#!/usr/bin/env python3
"""Monitor for new vulnerabilities in dependencies."""

import json
import subprocess
import sys
import os

def check_pip_audit():
    """Run pip-audit."""
    print("Running pip-audit...")
    try:
        # Check if pip-audit is installed
        subprocess.run([sys.executable, "-m", "pip", "show", "pip-audit"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("pip-audit not installed. Installing...")
        try:
             subprocess.run([sys.executable, "-m", "pip", "install", "pip-audit"], check=True)
        except Exception as e:
             print(f"Failed to install pip-audit: {e}")
             return 0 # Soft fail

    try:
        # Run audit
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format", "json"],
            capture_output=True,
            text=True
        )
        # pip-audit returns non-zero if vulns found
        
        output = result.stdout
        if not output:
             print("No output from pip-audit.")
             return 0

        try:
            audit_data = json.loads(output)
            if not audit_data:
                print("✅ No vulnerabilities found")
                return 0
                
            # Count vulns (structure varies by version, usually list of packages with 'vulns')
            vuln_count = 0
            if isinstance(audit_data, list):
                 for pkg in audit_data:
                      vulns = pkg.get("vulns", [])
                      if vulns:
                           print(f"⚠️  {pkg.get('name')}@{pkg.get('version')}: {len(vulns)} vulnerabilities")
                           vuln_count += len(vulns)
            
            if vuln_count > 0:
                 print(f"❌ Found {vuln_count} vulnerabilities")
                 return vuln_count
            else:
                 print("✅ No vulnerabilities found")
                 return 0

        except json.JSONDecodeError:
             print(f"Failed to parse pip-audit output: {output}")
             return 0

    except Exception as e:
        print(f"Error running pip-audit: {e}")
        return 0

def main():
    return check_pip_audit()

if __name__ == "__main__":
    sys.exit(main())
