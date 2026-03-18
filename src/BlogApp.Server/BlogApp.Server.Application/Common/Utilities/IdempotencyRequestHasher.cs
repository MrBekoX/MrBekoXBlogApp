using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace BlogApp.Server.Application.Common.Utilities;

public static class IdempotencyRequestHasher
{
    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false
    };

    public static string Compute(object request)
    {
        var json = JsonSerializer.Serialize(request, request.GetType(), SerializerOptions);
        var bytes = Encoding.UTF8.GetBytes(json);
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash);
    }
}
