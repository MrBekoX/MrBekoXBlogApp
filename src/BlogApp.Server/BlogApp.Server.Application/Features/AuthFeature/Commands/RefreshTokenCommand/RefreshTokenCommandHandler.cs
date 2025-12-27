using BlogApp.Server.Application.Common.Interfaces;
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

        // Refresh token'ı bul
        var storedToken = await unitOfWork.RefreshTokens.Query()
            .Include(t => t.User)
            .FirstOrDefaultAsync(t => t.Token == dto.RefreshToken, cancellationToken);

        if (storedToken is null)
        {
            return new RefreshTokenCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidRefreshToken)
            };
        }

        if (!storedToken.IsActive)
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

        // Eski token'ı iptal et
        storedToken.RevokedAt = DateTime.UtcNow;
        storedToken.RevokedByIp = dto.IpAddress;
        storedToken.ReasonRevoked = "Replaced by new token";

        // Yeni tokenlar oluştur
        var newAccessToken = jwtTokenService.GenerateAccessToken(user);
        var newRefreshToken = jwtTokenService.GenerateRefreshToken();

        storedToken.ReplacedByToken = newRefreshToken;

        // Yeni refresh token kaydet
        var refreshTokenEntity = new Domain.Entities.RefreshToken
        {
            Id = Guid.NewGuid(),
            Token = newRefreshToken,
            UserId = user.Id,
            ExpiresAt = DateTime.UtcNow.AddDays(7),
            CreatedAt = DateTime.UtcNow,
            CreatedByIp = dto.IpAddress
        };

        await unitOfWork.RefreshTokens.AddAsync(refreshTokenEntity, cancellationToken);
        unitOfWork.RefreshTokens.Update(storedToken);
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
