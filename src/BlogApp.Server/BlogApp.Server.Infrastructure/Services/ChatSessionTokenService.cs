using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Application.Common.Security;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;

namespace BlogApp.Server.Infrastructure.Services;

public sealed class ChatSessionTokenService(
    IOptions<JwtSettings> jwtSettings,
    IOptions<ChatSessionTokenSettings> chatSessionTokenSettings) : IChatSessionTokenService
{
    private readonly JwtSettings _jwtSettings = jwtSettings.Value;
    private readonly ChatSessionTokenSettings _chatSessionTokenSettings = chatSessionTokenSettings.Value;

    public ChatSessionTokenIssueResult IssueToken(ChatSessionTokenIssueRequest request)
    {
        var expiresAt = DateTimeOffset.UtcNow.AddMinutes(_chatSessionTokenSettings.ExpirationMinutes);
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_jwtSettings.Secret));
        var credentials = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, request.SessionId),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new(ChatSessionTokenDefaults.TokenUseClaim, ChatSessionTokenDefaults.TokenUseValue),
            new(ChatSessionTokenDefaults.SessionIdClaim, request.SessionId),
            new(ChatSessionTokenDefaults.PostIdClaim, request.PostId.ToString()),
            new(ChatSessionTokenDefaults.OperationIdClaim, request.OperationId),
            new(ChatSessionTokenDefaults.CorrelationIdClaim, request.CorrelationId)
        };

        if (!string.IsNullOrWhiteSpace(request.Fingerprint))
        {
            claims.Add(new Claim(ChatSessionTokenDefaults.FingerprintClaim, request.Fingerprint));
        }

        var token = new JwtSecurityToken(
            issuer: ChatSessionTokenDefaults.Issuer,
            audience: ChatSessionTokenDefaults.Audience,
            claims: claims,
            expires: expiresAt.UtcDateTime,
            signingCredentials: credentials);

        return new ChatSessionTokenIssueResult(
            new JwtSecurityTokenHandler().WriteToken(token),
            expiresAt);
    }
}
