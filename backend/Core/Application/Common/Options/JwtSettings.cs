using System.Text;

namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// JWT authentication configuration settings
/// </summary>
public sealed class JwtSettings
{
    public const string SectionName = "JwtSettings";

    private string _secret = string.Empty;

    public string Secret
    {
        get => _secret;
        init
        {
            if (string.IsNullOrWhiteSpace(value))
                throw new ArgumentException("JWT Secret cannot be null or empty", nameof(value));

            if (Encoding.UTF8.GetBytes(value).Length < 32)
                throw new ArgumentException("JWT Secret must be at least 256 bits (32 bytes) for security", nameof(value));

            _secret = value;
        }
    }
    
    public string Issuer { get; init; } = "BlogApp";
    public string Audience { get; init; } = "BlogApp";
    public int ExpirationMinutes { get; init; } = 60;
}

