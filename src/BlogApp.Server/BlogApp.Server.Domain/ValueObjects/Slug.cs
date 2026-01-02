using System.Text;
using System.Text.RegularExpressions;

namespace BlogApp.Server.Domain.ValueObjects;

/// <summary>
/// URL-friendly slug Value Object
/// </summary>
public sealed partial class Slug : IEquatable<Slug>
{
    public string Value { get; }

    private Slug(string value)
    {
        Value = value;
    }

    public static Slug Create(string slug)
    {
        if (string.IsNullOrWhiteSpace(slug))
            throw new ArgumentException("Slug cannot be empty", nameof(slug));

        slug = slug.Trim().ToLowerInvariant();

        if (!SlugRegex().IsMatch(slug))
            throw new ArgumentException("Invalid slug format. Slug can only contain lowercase letters, numbers, and hyphens.", nameof(slug));

        return new Slug(slug);
    }

    public static Slug CreateFromTitle(string title)
    {
        if (string.IsNullOrWhiteSpace(title))
            throw new ArgumentException("Title cannot be empty", nameof(title));

        var slug = GenerateSlug(title);
        return new Slug(slug);
    }

    private static string GenerateSlug(string title, int maxLength = 200)
    {
        // Türkçe karakterleri dönüştür
        var normalized = title.ToLowerInvariant();
        normalized = normalized.Replace("ş", "s").Replace("ğ", "g").Replace("ı", "i")
                              .Replace("ö", "o").Replace("ü", "u").Replace("ç", "c");

        // ASCII olmayan karakterleri kaldır
        var sb = new StringBuilder();
        foreach (var c in normalized)
        {
            if (c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == ' ' || c == '-')
                sb.Append(c);
        }

        // Boşlukları tire ile değiştir
        var result = sb.ToString().Trim();
        result = WhitespaceRegex().Replace(result, "-");

        // Ardışık tireleri tek tireye dönüştür
        result = MultipleHyphensRegex().Replace(result, "-");

        // Baştaki ve sondaki tireleri kaldır
        result = result.Trim('-');

        // Uzunluk kontrolü - maxLength'i aşarsa kes
        if (result.Length > maxLength)
        {
            result = result[..maxLength].TrimEnd('-');
        }

        return result;
    }

    [GeneratedRegex(@"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    private static partial Regex SlugRegex();

    [GeneratedRegex(@"\s+")]
    private static partial Regex WhitespaceRegex();

    [GeneratedRegex(@"-+")]
    private static partial Regex MultipleHyphensRegex();

    public bool Equals(Slug? other)
    {
        if (other is null) return false;
        return Value == other.Value;
    }

    public override bool Equals(object? obj) => obj is Slug slug && Equals(slug);
    public override int GetHashCode() => Value.GetHashCode();
    public override string ToString() => Value;

    public static implicit operator string(Slug slug) => slug.Value;
}
