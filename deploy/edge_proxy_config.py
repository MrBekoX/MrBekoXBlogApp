"""Generate explicit ALB transport trust and canonical upstream headers."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re


FORWARDING = """proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $forwarded_proto;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header Forwarded "";
proxy_set_header X-Original-For "";
proxy_set_header X-Original-Proto "";
proxy_set_header X-Forwarded-Prefix "";
"""


def trusted_networks(value: str) -> list[str]:
    entries = re.split(r"[\s,]+", value.strip())
    if not value.strip() or len(entries) > 32:
        raise ValueError("Configure 1-32 explicit ALB subnet CIDRs")
    result = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=True)
        except ValueError:
            raise ValueError("ALB_TRUSTED_CIDRS must contain canonical CIDRs only") from None
        if (network.prefixlen == 0 or network.is_multicast or network.network_address.is_unspecified
                or network.is_link_local):
            raise ValueError("Unrestricted or non-unicast ALB trust is not allowed")
        if (network.version == 4 and network.prefixlen < 16) or (network.version == 6 and network.prefixlen < 48):
            raise ValueError("Use narrow ALB subnet CIDRs, not broad VPC or Internet ranges")
        if str(network) not in result:
            result.append(str(network))
    return result


def render_trust(networks: list[str]) -> str:
    trust = "\n".join(f"set_real_ip_from {network};" for network in networks)
    allow = "\n".join(f"    {network} 1;" for network in networks)
    return f"""# Generated; the transport peer must be a configured ALB node subnet.
{trust}
real_ip_header X-Forwarded-For;
# ALB append mode places the actual client at the right edge. A single lookup
# avoids trusting attacker-supplied entries even for clients in an ALB subnet.
real_ip_recursive off;
geo $realip_remote_addr $trusted_ingress_peer {{
    default 0;
{allow}
}}
geo $realip_remote_addr $local_health_peer {{
    default 0;
    127.0.0.1/32 1;
    ::1/128 1;
}}
map "$local_health_peer:$uri" $local_health_request {{
    default 0;
    "1:/nginx-health" 1;
}}
map "$trusted_ingress_peer:$local_health_request" $ingress_allowed {{
    default 0;
    "1:0" 1;
    "1:1" 1;
    "0:1" 1;
}}
"""


def main() -> int:
    try:
        networks = trusted_networks(os.environ.get("ALB_TRUSTED_CIDRS", ""))
        output = Path(os.environ.get("EDGE_CONFIG_DIR", "/edge-config"))
        output.mkdir(parents=True, exist_ok=True)
        for name, content in (("forwarding.conf", FORWARDING), ("ingress.conf", render_trust(networks))):
            temporary = output / (name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(0o644)
            temporary.replace(output / name)
    except (ValueError, OSError) as error:
        print(str(error) if isinstance(error, ValueError) else "Cannot write edge proxy configuration")
        return 1
    print("Explicit ALB ingress trust configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
