"""B11 bileşik uçtan uca (E2E) test paketi.

Bu dizin B11 test sahipliğidir; kök ``tests/`` conftest'i değiştirilmez
(L005: ``tests/e2e`` __init__.py'li pakettir, conftest.py güvenlidir).

Ortam (L009 izolasyon kuralı — B11'e ÖZEL):
- Broker: ÖZEL vhost ``blogapp_w7_b11`` — B2/B3 (blogapp_dev), B4
  (blogapp_dev_b4), B6 (blogapp_w5_b6), B9 (blogapp_w6_b9) ve .NET B11
  (blogapp_w7_b11net) vhost'larıyla kuyruk paylaşımı yok.
- DB: ``blogdb_agent_b11_e2e`` scratch veritabanı; Alembic zinciri
  0001→0003 programatik ``upgrade head`` ile kurulur; her test tabloları
  truncate eder.
- Parola KODA GİRMEZ: docker/.env çalışma anında okunur (sır kuralı).

pytest-asyncio varsayımı YOKTUR: senkron testler paylaşımlı loop üstünde
``harness.run()`` ile koşar (B4/B6 deseni).
"""
