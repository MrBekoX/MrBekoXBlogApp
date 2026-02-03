"""Turkey GEO strategy - Optimization for Turkish market."""

from app.strategies.geo.base import IGeoStrategy


class TurkeyGeoStrategy(IGeoStrategy):
    """GEO optimization strategy for Turkey (TR)."""

    @property
    def region_code(self) -> str:
        return "TR"

    @property
    def region_name(self) -> str:
        return "Turkey"

    @property
    def primary_language(self) -> str:
        return "tr"

    def get_cultural_context(self) -> str:
        return """Türk okuyucusu samimi ve 'bizden' bir dil sever.
- Resmi olmayan ama saygılı bir ton tercih edilir
- Futbol ve güncel olaylar metaforları etkilidir
- Aile ve topluluk değerleri önemlidir
- Yerli ve milli duygular güçlüdür
- Pratik faydalar ve somut örnekler ilgi çeker"""

    def get_market_keywords(self) -> list[str]:
        return [
            "yerli",
            "milli",
            "kaliteli",
            "uygun fiyat",
            "garantili",
            "güvenilir",
            "Türkiye'de ilk",
            "en iyi",
            "ücretsiz",
            "hızlı",
            "kolay",
            "pratik",
        ]

    def get_seo_tips(self) -> str:
        return """Türkiye SEO İpuçları:
- Türkçe karakterleri (ı, ğ, ü, ş, ö, ç) doğru kullan
- Google.com.tr için optimize et
- Yerel arama terimlerini kullan (İstanbul, Ankara, vs.)
- Mobil öncelikli düşün (yüksek mobil kullanım)
- Sosyal medya paylaşım butonları önemli"""

    def get_content_style_guide(self) -> str:
        return """Türkiye İçerik Stili:
- 'Siz' yerine 'sen' hitabı daha samimi (blog için)
- Kısa paragraflar ve bullet point'ler
- Görsel içerik önemli
- Hikaye anlatımı ile bağ kur
- Sorulu cümleler ile etkileşim sağla"""
