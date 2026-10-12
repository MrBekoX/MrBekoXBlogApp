"""W5 bütünleştirme test paketi: gerçek JobStore × gerçek ControlStore.

B7 kontrol testleri sözleşmenin scratch DDL'ini (``tests/control/conftest.py``
B6_CONTRACT_DDL: fencing_token TEXT, status CHECK 'accepted'sız), B6 worker
testleri gerçek migration'ı kullanıyordu; iki tarafın GERÇEK store'ları hiçbir
testte aynı şemada bir arada koşmamıştı (W5 inceleme bulgusu 2). Bu paket o
boşluğu kapatır: gerçek alembic zinciri (0001→0003) kurulu TEK scratch DB
üstünde iptal yarışı terminal-öncelik kuralıyla doğrulanır.

L009 izolasyon kuralı: özel scratch DB (``blogdb_agent_w5int``); diğer
paketlerin DB/vhost'larına dokunulmaz. Senaryolar DB yarışı üzerindedir;
broker GEREKMEZ.
"""
