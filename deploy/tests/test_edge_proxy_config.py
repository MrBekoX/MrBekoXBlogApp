"""ALB trust and private API peer regression checks without infrastructure."""

import copy
import importlib.util
from pathlib import Path
import unittest

from test_preflight import module as preflight, release_config

spec = importlib.util.spec_from_file_location("edge_proxy_config", Path(__file__).parents[1] / "edge_proxy_config.py")
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)


class EdgeProxyTests(unittest.TestCase):
    def test_explicit_networks_have_one_alb_hop_and_original_peer_acl(self):
        networks = edge.trusted_networks("10.0.1.0/24, 2001:db8:10::/64,10.0.1.0/24")
        self.assertEqual(len(networks), 2)
        output = edge.render_trust(networks)
        self.assertIn("real_ip_recursive off;", output)
        self.assertIn("geo $realip_remote_addr $trusted_ingress_peer", output)
        self.assertIn("10.0.1.0/24 1;", output)
        self.assertNotIn("default 1;", output)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", edge.FORWARDING)
        self.assertNotIn("proxy_add_x_forwarded_for", edge.FORWARDING)

    def test_missing_broad_and_directive_injection_trust_is_rejected(self):
        for invalid in ("", "0.0.0.0/0", "::/0", "10.0.0.0/8", "2001::/16", "10.0.1.7/24",
                        "10.0.1.0/24;", "10.0.1.0/24\ninclude /etc/passwd;", "169.254.0.0/16"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                edge.trusted_networks(invalid)

    def test_raw_caller_cannot_widen_backend_or_share_trusted_network(self):
        baseline = release_config()
        self.assertEqual(preflight.validate_proxy_boundary(baseline), [])
        for mutation in (
            lambda c: c["services"]["api"]["environment"].update({"ForwardedHeaders__KnownProxies__0": "0.0.0.0"}),
            lambda c: c["services"]["api"]["environment"].update({"ForwardedHeaders__KnownProxies__1": "172.30.250.4"}),
            lambda c: c["services"]["frontend"].update({"networks": {"proxy-api": {}}}),
            lambda c: c["services"]["nginx"]["networks"].update({"default": {}}),
            lambda c: c["services"]["nginx"]["volumes"][0].update({"read_only": False}),
            lambda c: c["services"]["edge-config"]["environment"].update({"ALB_TRUSTED_CIDRS": "0.0.0.0/0"}),
        ):
            candidate = copy.deepcopy(baseline)
            mutation(candidate)
            self.assertTrue(preflight.validate_proxy_boundary(candidate))


if __name__ == "__main__":
    unittest.main()
