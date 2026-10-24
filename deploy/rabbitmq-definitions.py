"""Create salted RabbitMQ password hashes without printing or persisting secrets."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path


def password_hash(name: str) -> str:
    password = os.environ.get(name, "")
    if len(password) < 24 or password.lower().startswith(("change", "your", "example")):
        raise SystemExit(f"{name} must contain a unique secret of at least 24 characters")
    salt = os.urandom(4)
    return base64.b64encode(salt + hashlib.sha256(salt + password.encode()).digest()).decode()


def main() -> None:
    vhost = "blogapp_prod"
    identities = {
        "backend_svc": "RABBITMQ_BACKEND_PASSWORD",
        "agent_svc": "RABBITMQ_AGENT_PASSWORD",
        "topology_svc": "RABBITMQ_DECLARER_PASSWORD",
    }
    definitions = {
        "users": [
            {"name": user, "password_hash": password_hash(secret),
             "hashing_algorithm": "rabbit_password_hashing_sha256", "tags": []}
            for user, secret in identities.items()
        ],
        "vhosts": [{"name": vhost}],
        "permissions": [
            {"user": "backend_svc", "vhost": vhost, "configure": "",
             "write": r"^blog\.(agent\.commands|content\.events)$",
             "read": r"^backend\.agent\.events\.q(\.dlq)?$"},
            {"user": "agent_svc", "vhost": vhost, "configure": "",
             "write": r"^blog\.agent\.events$",
             "read": r"^agent\.(execute|control)(\.v2)?\.q(\.dlq)?$|^agent\.content\.q(\.dlq)?$"},
            # Used solely for declarations, never application event publishing.
            {"user": "topology_svc", "vhost": vhost, "configure": ".*",
             "write": ".*", "read": ".*"},
        ],
    }
    target = Path("/definitions/definitions.json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(definitions), encoding="utf-8")
    temporary.chmod(0o644)  # Salted hashes only; broker UID differs across image variants.
    temporary.replace(target)
    print("RabbitMQ role definitions prepared; credentials were not logged.")


if __name__ == "__main__":
    main()
