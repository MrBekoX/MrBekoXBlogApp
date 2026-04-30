using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService) : IRequestHandler<RefreshTokenCommandRequest, RefreshTokenCommandResponse>
{
    public async Task<RefreshTokenCommandResponse> Handle(RefreshTokenCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.RefreshTokenCommandRequestDto!;

        var storedToken = await unitOfWork.RefreshTokensRead.Query()
            .Include(t => t.User)
            .AsTracking()
            .FirstOrDefaultAsync(t => t.Token == dto.RefreshToken, cancellationToken);

        if (storedToken is null)
        {
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidRefreshToken)
            };
        }

        // Token reuse detection: if already revoked, someone is reusing a stolen token
        if (storedToken.IsRevoked)
        {
            // Revoke ALL tokens for this user as a security measure
            await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(storedToken.UserId, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidRefreshToken)
            };
        }

        if (storedToken.IsExpired)
        {
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.RefreshTokenExpired)
            };
        }

        var user = storedToken.User;
        if (user is null || !user.IsActive || user.IsDeleted)
        {
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.UserNotFound)
            };
        }

        // Atomically revoke the old token
        var revoked = await unitOfWork.RefreshTokensWrite.TryRevokeAsync(
            dto.RefreshToken, dto.IpAddress, "Replaced by new token", cancellationToken);

        if (!revoked)
        {
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidRefreshToken)
            };
        }

        // Generate new tokens
        var newAccessToken = jwtTokenService.GenerateAccessToken(user);
        var newRefreshToken = jwtTokenService.GenerateRefreshToken();

        // Link old -> new for family chain tracking
        storedToken.ReplacedByToken = newRefreshToken;

        var refreshTokenEntity = new Domain.Entities.RefreshToken
        {
            Id = Guid.NewGuid(),
            Token = newRefreshToken,
            UserId = user.Id,
            ExpiresAt = DateTime.UtcNow.AddDays(7),
            CreatedAt = DateTime.UtcNow,
            CreatedByIp = dto.IpAddress
        };

        await unitOfWork.RefreshTokensWrite.AddAsync(refreshTokenEntity, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new RefreshTokenCommandResponse
        {
            Result = Result<AuthResponseDto>.Success(new AuthResponseDto
            {
                AccessToken = newAccessToken,
                RefreshToken = newRefreshToken,
                ExpiresAt = jwtTokenService.GetTokenExpiration(newAccessToken),
                User = new UserInfoDto
                {
                    Id = user.Id,
                    UserName = user.UserName,
                    Email = user.Email,
                    FullName = user.FullName,
                    AvatarUrl = user.AvatarUrl,
                    Role = user.Role.ToString()
                }
            })
        };
    }
}



