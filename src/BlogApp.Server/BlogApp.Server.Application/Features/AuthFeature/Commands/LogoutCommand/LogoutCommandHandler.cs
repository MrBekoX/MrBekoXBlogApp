using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LogoutCommand;

public class LogoutCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService,
    ITokenBlacklistService tokenBlacklist) : IRequestHandler<LogoutCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(LogoutCommandRequest request, CancellationToken cancellationToken)
    {
        // Blacklist the access token so it cannot be reused
        if (!string.IsNullOrEmpty(request.AccessToken))
        {
            try
            {
                var expiration = jwtTokenService.GetTokenExpiration(request.AccessToken);
                var remaining = expiration - DateTime.UtcNow;
                if (remaining > TimeSpan.Zero)
                {
                    var jti = jwtTokenService.GetTokenJti(request.AccessToken);
                    if (!string.IsNullOrEmpty(jti))
                        await tokenBlacklist.BlacklistTokenAsync(jti, remaining, cancellationToken);
                }
            }
            catch
            {
                // Token parsing failure is non-critical for logout
            }
        }

        if (string.IsNullOrEmpty(request.RefreshToken))
        {
            return Result<Unit>.Success(Unit.Value);
        }

        // Find the token to get the user ID
        var storedToken = await unitOfWork.RefreshTokensRead.GetSingleAsync(
            t => t.Token == request.RefreshToken, cancellationToken);

        if (storedToken != null)
        {
            // Revoke ALL active tokens for this user (not just the current one)
            await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(storedToken.UserId, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }

        return Result<Unit>.Success(Unit.Value);
    }
}
