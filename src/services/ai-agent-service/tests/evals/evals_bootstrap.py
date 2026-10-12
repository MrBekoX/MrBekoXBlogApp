"""tests/evals duman testlerinin yol kurulumu (L005 kuralı).

``tests/evals`` ``__init__.py``'li paket DEĞİLDİR; bu yüzden conftest.py
açılmaz ve yardımcılar adlandırılmış modülde yaşar. Bu modül, koşucu
paketinin (``<hizmet-kökü>/evals``) ve ``agent_core``'un (``app/``)
import edilebilmesi için sys.path'i kurar; testler en başta
``import evals_bootstrap`` yapar.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]

for _path in (_SERVICE_ROOT, _SERVICE_ROOT / "app"):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)


def service_root() -> Path:
    return _SERVICE_ROOT
