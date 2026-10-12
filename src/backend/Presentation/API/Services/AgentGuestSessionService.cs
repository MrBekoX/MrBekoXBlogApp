using BlogApp.Core.Application.Common.Interfaces.Services;

namespace BlogApp.Presentation.Api.Services;

/// <summary>
/// Sunucu tarafı misafir oturumu (K5, plan satır 124: kimlik doğrulama yalnız
/// JWT + sunucu üretiği misafir oturumu; istemcinin owner alanı yetki kaynağı
/// değildir). Misafir kimliği HttpOnly çerezle taşınır: JavaScript okuyamaz,
/// değer sunucu üretir ve yalnız run sahipliği hesabında kullanılır.
/// Doğrulanmış kullanıcıda yok sayılır (owner anahtarı ``u:{userId}``).
/// </summary>
public interface IAgentGuestSessionService
{
    /// <summary>Misafir oturum kimliğini okur; yoksa üretip çerez yazar (POST kabul yolu).</summary>
    string GetOrAssignGuestSessionId();

    /// <summary>Misafir oturum kimliğini yalnız okur (GET yolları; çerez üretmez).</summary>
    string? GetGuestSessionId();
}

public sealed class AgentGuestSessionService(IHttpContextAccessor httpContextAccessor) : IAgentGuestSessionService
{
    public const string CookieName = "blogapp_agent_guest";
    private static readonly TimeSpan CookieLifetime = TimeSpan.FromDays(180);

    public string GetOrAssignGuestSessionId()
    {
        var context = httpContextAccessor.HttpContext
            ?? throw new InvalidOperationException("Misafir oturumu yalnız HTTP istek bağlamında çözülür.");

        var userId = context.User.GetAgentUserIdFromPrincipal();
        if (userId is not null)
        {
            // Doğrulanmış kullanıcı: misafir çerezi yok sayılır (K5: kullanıcı önceliklidir).
            return string.Empty;
        }

        if (TryReadCookie(context, out var existing))
        {
            return existing;
        }

        var guestSessionId = Guid.NewGuid().ToString("D");
        // Secure: UseForwardedHeaders X-Forwarded-Proto'yü uygular (prod ters proxy arkası
        // https görünür); yerel http geliştirmede false kalır.
        context.Response.Cookies.Append(CookieName, guestSessionId, new CookieOptions
        {
            HttpOnly = true,
            Secure = context.Request.IsHttps,
            SameSite = SameSiteMode.Lax,
            IsEssential = true,
            MaxAge = CookieLifetime,
            Path = "/",
        });
        return guestSessionId;
    }

    public string? GetGuestSessionId()
    {
        var context = httpContextAccessor.HttpContext;
        if (context is null)
        {
            return null;
        }

        return TryReadCookie(context, out var value) ? value : null;
    }

    private static bool TryReadCookie(HttpContext context, out string guestSessionId)
    {
        guestSessionId = string.Empty;
        var raw = context.Request.Cookies[CookieName];
        if (string.IsNullOrWhiteSpace(raw) || raw.Length > 64)
        {
            return false;
        }

        // Kanonik UUID: bozuk/uydurma çerez değeri oturum sayılmaz (yeni çerez üretilir).
        if (!Guid.TryParseExact(raw, "D", out _))
        {
            return false;
        }

        guestSessionId = raw;
        return true;
    }
}

/// <summary>Kimlik çözümleme yardımı (Presentation tarafı; JWT claim'leri).</summary>
public static class AgentIdentityExtensions
{
    public static Guid? GetAgentUserIdFromPrincipal(this System.Security.Claims.ClaimsPrincipal? principal) =>
        principal?.FindFirst("userId") is { } claim && Guid.TryParse(claim.Value, out var userId)
            ? userId
            : null;
}
