import time
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime
from enum import Enum
import logging

try:
    from app.security.audit_logger import audit_logger
except ImportError:
    # Fallback or mock if audit logger isn't strictly ready
    audit_logger = None

logger = logging.getLogger(__name__)

class AnomalyType(str, Enum):
    """Types of anomalies."""
    RATE_SPIKE = "rate_spike"
    BURST_PATTERN = "burst_pattern"
    UNUSUAL_TIME = "unusual_time"
    GEO_ANOMALY = "geo_anomaly"
    TOKEN_ANOMALY = "token_anomaly"
    FAILURES_SPIKE = "failures_spike"

@dataclass
class AnomalyEvent:
    """Anomaly detection event."""
    anomaly_type: AnomalyType
    user_id: str
    severity: str  # low, medium, high, critical
    score: float
    timestamp: datetime
    details: dict
    alerts_sent: List[str] = field(default_factory=list)

class AnomalyDetector:
    """Behavioral anomaly detection."""

    MAX_TRACKED_USERS = 10000
    STALE_THRESHOLD_SECONDS = 3600  # 1 hour
    CLEANUP_INTERVAL = 100  # run cleanup every N requests

    def __init__(
        self,
        window_seconds: int = 60,
        burst_threshold_ms: int = 100,
        rate_spike_threshold: int = 100,
        alert_callback=None
    ):
        self.window_seconds = window_seconds
        self.burst_threshold_ms = burst_threshold_ms
        self.rate_spike_threshold = rate_spike_threshold
        self.alert_callback = alert_callback

        # User request history
        self.user_requests: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

        # User failure history
        self.user_failures: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

        # Baseline statistics
        self.baselines: Dict[str, dict] = {}

        # Lock for thread safety
        self.lock = asyncio.Lock()

        # Counter for periodic cleanup
        self._request_count = 0

    async def record_request(
        self,
        user_id: str,
        success: bool = True,
        token_count: int = 0,
        ip_address: str = None
    ) -> Optional[AnomalyEvent]:
        """Record a request and check for anomalies."""
        now = time.time()

        async with self.lock:
            # Periodic cleanup of stale user data
            self._request_count += 1
            if self._request_count % self.CLEANUP_INTERVAL == 0:
                self._cleanup_stale_users(now)

            # Record request
            self.user_requests[user_id].append({
                "timestamp": now,
                "success": success,
                "tokens": token_count,
                "ip": ip_address
            })

            if not success:
                self.user_failures[user_id].append(now)

            # Check for anomalies
            anomaly = await self._check_anomalies(user_id)

            if anomaly:
                await self._handle_anomaly(anomaly)
                return anomaly

        return None

    def _cleanup_stale_users(self, now: float) -> None:
        """Remove users with no recent activity to prevent unbounded memory growth."""
        stale_users = []
        for user_id, requests in self.user_requests.items():
            if requests and (now - requests[-1]["timestamp"]) > self.STALE_THRESHOLD_SECONDS:
                stale_users.append(user_id)
            elif not requests:
                stale_users.append(user_id)

        for user_id in stale_users:
            del self.user_requests[user_id]
            self.user_failures.pop(user_id, None)
            self.baselines.pop(user_id, None)

        # Hard cap: if still over limit, evict oldest entries
        if len(self.user_requests) > self.MAX_TRACKED_USERS:
            sorted_users = sorted(
                self.user_requests.items(),
                key=lambda kv: kv[1][-1]["timestamp"] if kv[1] else 0
            )
            excess = len(self.user_requests) - self.MAX_TRACKED_USERS
            for user_id, _ in sorted_users[:excess]:
                del self.user_requests[user_id]
                self.user_failures.pop(user_id, None)
                self.baselines.pop(user_id, None)

        if stale_users:
            logger.info(f"Cleaned up {len(stale_users)} stale user records")

    async def _check_anomalies(self, user_id: str) -> Optional[AnomalyEvent]:
        """Check for various anomaly types."""
        requests = self.user_requests[user_id]
        now = time.time()

        # Get recent requests
        recent = [
            r for r in requests
            if now - r["timestamp"] <= self.window_seconds
        ]

        if not recent:
            return None

        # 1. Rate Spike Detection
        if len(recent) > self.rate_spike_threshold:
            baseline = self._get_baseline(user_id)
            avg_rate = baseline.get("avg_requests_per_minute", 10)

            if len(recent) > avg_rate * 5 and len(recent) > 20:  # 5x normal rate AND significant volume
                return AnomalyEvent(
                    anomaly_type=AnomalyType.RATE_SPIKE,
                    user_id=user_id,
                    severity="high",
                    score=min(len(recent) / avg_rate, 1.0),
                    timestamp=datetime.now(),
                    details={
                        "current_rate": len(recent),
                        "baseline_rate": avg_rate,
                        "window": self.window_seconds
                    }
                )

        # 2. Burst Pattern Detection
        if self._check_burst_pattern(recent):
            return AnomalyEvent(
                anomaly_type=AnomalyType.BURST_PATTERN,
                user_id=user_id,
                severity="medium",
                score=0.8,
                timestamp=datetime.now(),
                details={
                    "burst_count": self._count_bursts(recent),
                    "threshold_ms": self.burst_threshold_ms
                }
            )

        # 3. Failure Spike Detection
        failures = self.user_failures[user_id]
        recent_failures = [
            f for f in failures
            if now - f <= self.window_seconds
        ]

        if len(recent_failures) > 10:  # More than 10 failures in window
            failure_rate = len(recent_failures) / len(recent) if recent else 0

            if failure_rate > 0.5:  # More than 50% failures
                return AnomalyEvent(
                    anomaly_type=AnomalyType.FAILURES_SPIKE,
                    user_id=user_id,
                    severity="critical",
                    score=failure_rate,
                    timestamp=datetime.now(),
                    details={
                        "failures": len(recent_failures),
                        "total_requests": len(recent),
                        "failure_rate": failure_rate
                    }
                )

        # Update baseline
        self._update_baseline(user_id, recent)

        return None

    def _check_burst_pattern(self, requests: List[dict]) -> bool:
        """Check for burst pattern (multiple requests in short time)."""
        if len(requests) < 5: # Need enough data
            return False

        # Sort recent (they should be sorted by append but just in case)
        # deque is ordered.
        
        # Check for 3 requests within burst_threshold_ms
        # We need to look at specific sequence
        burst_threshold_sec = self.burst_threshold_ms / 1000.0
        
        for i in range(len(requests) - 2):
            t1 = requests[i]["timestamp"]
            t3 = requests[i + 2]["timestamp"]
            
            if (t3 - t1) < burst_threshold_sec:
                return True
        return False

    def _count_bursts(self, requests: List[dict]) -> int:
        """Count number of burst sequences."""
        # Simplified count
        return 1 if self._check_burst_pattern(requests) else 0

    def _get_baseline(self, user_id: str) -> dict:
        """Get baseline statistics for user."""
        if user_id not in self.baselines:
            self.baselines[user_id] = {
                "avg_requests_per_minute": 10,
                "active_hours": list(range(8, 18)),  # 8 AM - 6 PM
            }
        return self.baselines[user_id]

    def _update_baseline(self, user_id: str, recent_requests: List[dict]):
        """Update baseline statistics."""
        if user_id not in self.baselines:
            self.baselines[user_id] = {}

        baseline = self.baselines[user_id]
        
        # Simple rolling average update
        current_rate = len(recent_requests)
        if "avg_requests_per_minute" not in baseline:
             baseline["avg_requests_per_minute"] = current_rate
        else:
             baseline["avg_requests_per_minute"] = (0.9 * baseline["avg_requests_per_minute"]) + (0.1 * current_rate)

    async def _handle_anomaly(self, anomaly: AnomalyEvent):
        """Handle detected anomaly."""
        logger.warning(
            f"Anomaly detected: type={anomaly.anomaly_type}, "
            f"user={anomaly.user_id}, severity={anomaly.severity}, "
            f"score={anomaly.score:.2f}"
        )

        try:
            from app.monitoring.metrics import anomalies_detected, anomaly_scores
            anomalies_detected.labels(type=anomaly.anomaly_type.value, severity=anomaly.severity).inc()
            anomaly_scores.observe(anomaly.score)
        except ImportError:
            pass

        # Log to audit (if available)
        if audit_logger and anomaly.severity in ["high", "critical"]:
            await audit_logger.log_event(
                event_type="anomaly_detected",
                user_id=anomaly.user_id,
                resource_id=anomaly.anomaly_type.value,
                action="detection",
                success=False,
                details={
                    "severity": anomaly.severity,
                    "score": anomaly.score,
                    "anomaly_details": anomaly.details
                }
            )

        # Send alert via callback
        if self.alert_callback:
            try:
                await self.alert_callback(anomaly)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

# Singleton if needed
anomaly_detector = AnomalyDetector()
