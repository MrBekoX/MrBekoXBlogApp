namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Canonical yazar profili konumu — appsettings "AuthorProfile" section (K2).
/// Boşsa <c>AppContext.BaseDirectory/content/author-profile</c> kullanılır (API csproj
/// src/content/author-profile/** dosyalarını build/publish çıktısına bu yola kopyalar).
/// Göreli değer AppContext.BaseDirectory'ye göre çözülür; çalışma dizini (cwd) KULLANILMAZ.
/// </summary>
public sealed class AuthorProfileSettings
{
    public const string SectionName = "AuthorProfile";

    public string? Directory { get; set; }
}
