"""Ortak başlık anchor sözleşmesi (A3).

Kural kümesi ``tests/content/fixtures.py`` içindeki ortak fixture'larla
sabitlenmiştir; chunker ve retrieval aynı fonksiyonları kullanır:

1. Türkçe karakterler önce katlanır: ``ç→c, ğ→g, ı→i, İ→i, ö→o, ş→s, ü→u``
   (büyük halleri dahil; ``I→i``). Ardından ``casefold`` uygulanır; sıra
   önemlidir çünkü ``İ``'nin casefold'u birleşik nokta üretir.
2. ``[a-z0-9]`` dışındaki her karakter ``-`` olur; art arda ``-`` tek ``-``'e
   iner; baş/son ``-`` atılır.
3. Boş kalan slug ``bolum`` yedek değerini alır (yalnız noktalama içeren
   başlıklar için deterministik çıkış).
4. Aynı makalede aynı base slug tekrar ederse 2. oluşum ``-2``, 3. oluşum
   ``-3`` ... son ekini alır; sayaç tek geçişte belge sırasına göre işler.

Anchor değerleri canonical URL fragment'larında kullanılır; aynı başlık her
zaman aynı anchor'ı üretir (determinizm kabul ölçütü: "Başlık anchor'ları
ortak fixture'larla doğrulanıyor").
"""

from __future__ import annotations

_TR_FOLD = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "I": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)

#: Yalnız noktalama/boşluktan oluşan başlıklar için yedek slug.
EMPTY_SLUG_FALLBACK = "bolum"

__all__ = ["EMPTY_SLUG_FALLBACK", "fold_text", "heading_anchor", "slugify_heading"]


def fold_text(text: str) -> str:
    """Türkçe katlama + casefold; anahtar kelime eşleştirmesi de bunu kullanır."""

    return text.translate(_TR_FOLD).casefold()


def slugify_heading(heading: str) -> str:
    """Base slug üretir; tekrarlanan başlık ayrımı yapılmaz (bkz. ``heading_anchor``)."""

    folded = fold_text(heading)
    chars: list[str] = []
    for ch in folded:
        chars.append(ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else "-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or EMPTY_SLUG_FALLBACK


def heading_anchor(heading: str, seen: dict[str, int]) -> str:
    """Başlığın anchor'ını döndürür; ``seen`` sayacı belge sırasıyla güncellenir.

    Args:
        heading: Başlık metni (başlık yolunun son ögesi).
        seen: base slug → o ana kadarki oluşum sayısı; çağıran tek makalelik
            tek geçişte aynı sözlüğü paylaşır.
    """

    base = slugify_heading(heading)
    count = seen.get(base, 0) + 1
    seen[base] = count
    return base if count == 1 else f"{base}-{count}"
