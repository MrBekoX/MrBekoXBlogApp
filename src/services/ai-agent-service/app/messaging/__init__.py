"""Transport katmanı: RabbitMQ üzerinden backend (.NET) ile agent çekirdeği arasındaki taşıma.

Bu paket agent iş modellerinin (``agent_core``) DIŞINDADIR; yön tek yönlüdür
(messaging → agent_core izinli, tersi yasak — W0 Ç2). Broker envelope'u yalnız
burada bilinir; agent_core transport kavramı görmez.
"""
