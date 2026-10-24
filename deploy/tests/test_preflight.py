"""Configuration acceptance gates; no containers, credentials or providers used."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("deploy_preflight", Path(__file__).parents[1] / "preflight.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def release_config() -> dict:
    config = {"services": {
        "postgres": {"environment": {"POSTGRES_USER": "blogapp", "POSTGRES_DB": "blogdb",
                                        "POSTGRES_PASSWORD": "p" * 48}},
        "redis": {"environment": {"REDISCLI_AUTH": "r" * 48}},
        "rabbitmq": {},
        "rabbitmq-definitions": {"environment": {"RABBITMQ_BACKEND_PASSWORD": "b" * 48,
                                                      "RABBITMQ_AGENT_PASSWORD": "a" * 48,
                                                      "RABBITMQ_DECLARER_PASSWORD": "d" * 48}},
        "agent-migrate": {"image": "registry/blog:agent-1234567"},
        "api": {"image": "registry/blog:api-1234567", "environment": {
            "JwtSettings__Secret": "j" * 64, "AdminUser__Password": "admin-real-secret-123",
            "AdminUser__Email": "admin@blog.test", "AgentService__InternalApiKey": "i" * 48}},
        "ai-agent": {"image": "registry/blog:agent-1234567", "environment": {
            "AGENT_LLM_API_KEY": "sk-local-validation-key", "AGENT_LLM_MODEL": "selected-model",
            "AGENT_LLM_BASE_URL": "https://api.openai.com/v1", "AGENT_EMBEDDING_API_KEY": "",
            "AGENT_EMBEDDING_MODEL": "text-embedding-3-small", "AGENT_EMBEDDING_DIMENSIONS": "1536",
            "AGENT_CONTENT_BASE_URL": "http://api:8080/api/v1", "AGENT_CONTENT_SERVICE_KEY": "i" * 48,
            "AGENT_TOPOLOGY_DECLARE": "false"}},
        "frontend": {"image": "registry/blog:web-1234567"},
        "nginx": {"environment": {"DOMAIN": "blog.test"},
                  "networks": {"proxy-api": {"ipv4_address": "172.30.250.2"}, "proxy-web": {}},
                  "volumes": [{"type": "volume", "source": "edge", "target": "/etc/nginx/trusted", "read_only": True}]},
        "edge-config": {"network_mode": "none", "environment": {"ALB_TRUSTED_CIDRS": "10.0.1.0/24"},
                        "volumes": [{"type": "volume", "source": "edge", "target": "/edge-config"}]},
    }}
    config["networks"] = {"proxy-api": {"internal": True, "ipam": {"config": [{"subnet": "172.30.250.0/29"}]}}}
    config["services"]["api"]["networks"] = {"default": {}, "proxy-api": {"ipv4_address": "172.30.250.3"}}
    config["services"]["api"]["environment"].update({
        "ForwardedHeaders__Enabled": "true", "ForwardedHeaders__KnownProxies__0": "172.30.250.2"})
    for service, target in (("api", "/app/content/author-profile"),
                            ("ai-agent", "/srv/content/author-profile")):
        config["services"][service]["volumes"] = [{
            "type": "bind", "source": "/opt/blogapp-private/author-profile", "target": target,
            "read_only": True, "bind": {"create_host_path": False}}]
    return config


class PreflightTests(unittest.TestCase):
    def test_complete_release_passes(self):
        self.assertEqual([], module.validate_config(release_config()))

    def test_missing_and_placeholder_credentials_fail_without_echoing_secret(self):
        for invalid in ("", "CHANGE_ME_" + "private" * 20, "your-production-password"):
            config = release_config()
            config["services"]["api"]["environment"]["JwtSettings__Secret"] = invalid
            errors = module.validate_config(config)
            self.assertTrue(errors)
            if invalid:
                self.assertNotIn(invalid, " ".join(errors))

    def test_external_llm_requires_separate_openai_key(self):
        config = release_config()
        env = config["services"]["ai-agent"]["environment"]
        env["AGENT_LLM_BASE_URL"] = "https://another-provider.test/v1"
        self.assertTrue(module.validate_config(config))
        env["AGENT_EMBEDDING_API_KEY"] = "sk-openai-key-for-validation"
        self.assertEqual([], module.validate_config(config))

    def test_release_and_migration_drift_fail(self):
        for service in ("api", "frontend", "ai-agent", "agent-migrate"):
            config = release_config()
            config["services"][service]["image"] += "-different-release"
            self.assertTrue(module.validate_config(config), service)

    def test_auth_model_topology_and_domain_errors_are_rejected(self):
        for key, value in (("AGENT_CONTENT_SERVICE_KEY", "different"),
                           ("AGENT_EMBEDDING_MODEL", "hashing"),
                           ("AGENT_EMBEDDING_DIMENSIONS", "8"),
                           ("AGENT_TOPOLOGY_DECLARE", "true")):
            config = release_config()
            config["services"]["ai-agent"]["environment"][key] = value
            self.assertTrue(module.validate_config(config), key)
        config = release_config()
        config["services"]["nginx"]["environment"]["DOMAIN"] = 'blog.test; include /etc/secrets;'
        self.assertTrue(module.validate_config(config))

    def test_broker_credentials_must_be_distinct(self):
        config = release_config()
        credentials = config["services"]["rabbitmq-definitions"]["environment"]
        credentials["RABBITMQ_AGENT_PASSWORD"] = credentials["RABBITMQ_BACKEND_PASSWORD"]
        self.assertTrue(module.validate_config(config))

    def test_profile_bundle_mounts_are_required_readonly_existing_and_identical(self):
        for mutation in (
            lambda mount: mount.update(source="relative/private/profile"),
            lambda mount: mount.update(source="/opt/different-profile"),
            lambda mount: mount.update(read_only=False),
            lambda mount: mount.update(type="volume"),
            lambda mount: mount["bind"].update(create_host_path=True),
            # Older exporters can omit false; newer exporters can omit true.
            # An ambiguous projection must not authorize directory creation.
            lambda mount: mount.update(bind={}),
            lambda mount: mount.pop("bind"),
            lambda mount: mount.update(bind=None),
            lambda mount: mount["bind"].update(create_host_path=None),
        ):
            config = release_config()
            mutation(config["services"]["ai-agent"]["volumes"][0])
            self.assertTrue(module.validate_config(config))
        config = release_config()
        config["services"]["api"].pop("volumes")
        self.assertTrue(module.validate_config(config))

    def test_host_profile_gate_rejects_tracked_example_without_echoing_identity(self):
        sample = Path(__file__).resolve().parents[2] / "src/content/author-profile"
        errors = module.validate_private_profile(str(sample))
        self.assertTrue(errors)
        self.assertNotIn("Sample Author", " ".join(errors))

    def test_host_profile_gate_rejects_absent_bundle(self):
        self.assertTrue(module.validate_private_profile(""))


if __name__ == "__main__":
    unittest.main()
