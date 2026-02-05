from prometheus_client import Counter, Histogram, Gauge

# Anomaly metrics
anomalies_detected = Counter(
    'anomalies_detected_total',
    'Total anomalies detected',
    ['type', 'severity']
)

anomaly_scores = Histogram(
    'anomaly_detection_score',
    'Anomaly detection scores',
    buckets=[0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
)

active_investigations = Gauge(
    'active_security_investigations',
    'Number of active security investigations'
)

user_request_rate = Histogram(
    'user_request_rate',
    'User request rate per minute',
    buckets=[1, 5, 10, 25, 50, 100, 250]
)
