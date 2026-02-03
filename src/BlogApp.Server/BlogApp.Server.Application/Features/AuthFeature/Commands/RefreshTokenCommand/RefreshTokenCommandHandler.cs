using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;
using System.Data;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;

public class RefreshTokenCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService) : IRequestHandler<RefreshTokenCommandRequest, RefreshTokenCommandResponse>
{
    public async Task<RefreshTokenCommandResponse> Handle(RefreshTokenCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.RefreshTokenCommandRequestDto!;

        // Use transaction to prevent race conditions
        using var transaction = await unitOfWork.BeginTransactionAsync(IsolationLevel.Serializable, cancellationToken);
        
        try
        {
            // Refresh token'ı bul ve lock'la
            var storedToken = await unitOfWork.RefreshTokensRead.Query()
                .Include(t => t.User)
                .FirstOrDefaultAsync(t => t.Token == dto.RefreshToken, cancellationToken);

            if (storedToken is null)
            {
                await transaction.RollbackAsync(cancellationToken);
                return new RefreshTokenCommandResponse
                {
                    Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidRefreshToken)
                };
            }

            if (!storedToken.IsActive)
            {
                await transaction.RollbackAsync(cancellationToken);
                return new RefreshTokenCommandResponse
                {
                    Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.RefreshTokenExpired)
                };
            }

            var user = storedToken.User;
            if (user is null || !user.IsActive || user.IsDeleted)
            {
                await transaction.RollbackAsync(cancellationToken);
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

            await unitOfWork.RefreshTokensWrite.AddAsync(refreshTokenEntity, cancellationToken);
            await unitOfWork.RefreshTokensWrite.UpdateAsync(storedToken, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);
            
            await transaction.CommitAsync(cancellationToken);

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
        catch
        {
            await transaction.RollbackAsync(cancellationToken);
            throw;
        }
    }
}



