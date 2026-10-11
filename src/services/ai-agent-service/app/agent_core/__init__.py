"""Agent çekirdeği (``agent_core``).

Dış transport'a bağımsız iş modelleri, port arayüzleri, deterministik router
ve üç uygulama girişi. Bağımlılık yönü: ``agent_core`` → hiçbir dış transport
modülü (``app.messaging`` B1'de gelir ve yalnız ``agent_core``'u import eder).
"""

from . import adapters, errors, models, ports
from .entrypoints import PreparedRun, ResumeRequest, execute_plan, prepare_and_route, resume
from .routing import decide_mode, route_for_context

__all__ = [
    "PreparedRun",
    "ResumeRequest",
    "adapters",
    "decide_mode",
    "errors",
    "execute_plan",
    "models",
    "ports",
    "prepare_and_route",
    "resume",
    "route_for_context",
]
