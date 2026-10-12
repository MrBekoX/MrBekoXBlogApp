"""A9 site rehberliği ve iş birliği hazırlığı testleri (plan A9).

``__init__.py``'li paket (L005): conftest.py yalnız paket içinde güvenlidir.
Tüm akışlar test double/fikstür verisiyle koşar; gerçek LLM/katalog yoktur —
double başarısı gerçek sağlayıcı başarısı sayılmaz (ana prompt kuralı).
Async akışlar kök kural gereği ``run()`` ile senkron çağrılır.
"""
