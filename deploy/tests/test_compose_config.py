"""Validate the actual production Compose wiring with nonsecret test values."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("preflight", DEPLOY / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class ComposeConfigTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI is required; no daemon or containers are used")
    def test_actual_production_compose_satisfies_configuration_gate(self):
        env = dict(os.environ, DOMAIN="ci.example.test", IMAGE_REPOSITORY="validation/blog-app", RELEASE_TAG="ci-validation",
            POSTGRES_USER="blogapp_user", POSTGRES_DB="blogdb", POSTGRES_PASSWORD="d" * 32,
            REDIS_PASSWORD="r" * 32, JWT_SECRET="j" * 64, ADMIN_EMAIL="owner@ci.example.test", ADMIN_PASSWORD="p" * 24,
            AGENT_CONTENT_SERVICE_KEY="c" * 64, AGENT_LLM_API_KEY="k" * 48, AGENT_LLM_MODEL="ci-selected-chat-model",
            AGENT_LLM_BASE_URL="https://api.openai.com/v1", AGENT_EMBEDDING_API_KEY="",
            RABBITMQ_BACKEND_PASSWORD="b" * 32, RABBITMQ_AGENT_PASSWORD="a" * 32, RABBITMQ_DECLARER_PASSWORD="t" * 32,
            AUTHOR_PROFILE_HOST_DIR="/opt/blogapp-private/author-profile")
        result = subprocess.run(["docker", "compose", "--env-file", str(DEPLOY / ".env.example"),
            "-f", str(DEPLOY / "docker-compose.prod.yml"), "config", "--format", "json", "--no-path-resolution"],
            env=env, capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(preflight.validate_config(json.loads(result.stdout)), [])


if __name__ == "__main__":
    unittest.main()
