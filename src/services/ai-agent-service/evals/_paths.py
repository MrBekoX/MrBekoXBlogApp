"""Paket yol kurulumu: agent_core'un import edilebilmesi için sys.path.

``evals`` paketi ``src/services/ai-agent-service/evals`` altında yaşar;
``agent_core`` ise aynı dizinin ``app/`` altındadır. Pytest ``pythonpath =
["app"]`` (pyproject) ayarıyla koşar; ``python -m evals.run`` ise hizmet
kökünden çalıştırıldığında yalnız hizmet kökünü görür. Bu modül her iki
yolu da garantiye alır; kimseyi ezmeden başa ekler.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_APP_DIR = _SERVICE_ROOT / "app"


def ensure_service_paths() -> None:
    """``app/`` ve hizmet kökünü sys.path başına (idempotent) ekler."""
    for path in (_SERVICE_ROOT, _APP_DIR):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def service_root() -> Path:
    """Hizmet kökünü döndürür (rapor çıktılarının varsayılan yeri için)."""
    return _SERVICE_ROOT
