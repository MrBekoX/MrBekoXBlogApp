"""Production dotenv opt-out must work without reading developer credentials."""

import os
from env_file import load_env_file


def test_explicit_null_device_disables_dotenv_discovery():
    assert load_env_file(os.devnull) == {}
