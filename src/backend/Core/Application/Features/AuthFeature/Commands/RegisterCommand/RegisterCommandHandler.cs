using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using BlogApp.Core.Application.Features.AuthFeature.Rules;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.RegisterCommand;

public class RegisterCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService,
    IAuthBusinessRules authBusinessRules) : IRequestHandler<RegisterCommandRequest, Result<AuthResponseDto>>
{
    public async Task<Result<AuthResponseDto>> Handle(RegisterCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.RegisterCommandRequestDto!;

        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await authBusinessRules.CheckEmailIsUniqueAsync(dto.Email),
            async () => await authBusinessRules.CheckUserNameIsUniqueAsync(dto.UserName)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<AuthResponseDto>.Failure(Error.Conflict(ruleResult.Error!));
        }

        // Kullanıcı oluştur
        var user = new User
        {
            Id = Guid.NewGuid(),
            UserName = dto.UserName,
            Email = dto.Email.ToLower(),
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.Password, workFactor: 12),
            FirstName = dto.FirstName,
            LastName = dto.LastName,
            Role = UserRole.Reader,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            LastLoginAt = DateTime.UtcNow
        };

        await unitOfWork.UsersWrite.AddAsync(user, cancellationToken);

        // Token oluştur
        var accessToken = jwtTokenService.GenerateAccessToken(user);
        var refreshToken = jwtTokenService.GenerateRefreshToken();

        // Refresh token kaydet
        var refreshTokenEntity = new Domain.Entities.RefreshToken
        {
            Id = Guid.NewGuid(),
            Token = refreshToken,
            UserId = user.Id,
            ExpiresAt = DateTime.UtcNow.AddDays(7),
            CreatedAt = DateTime.UtcNow,
            CreatedByIp = dto.IpAddress
        };

        await unitOfWork.RefreshTokensWrite.AddAsync(refreshTokenEntity, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<AuthResponseDto>.Success(new AuthResponseDto
        {
            AccessToken = accessToken,
            RefreshToken = refreshToken,
            ExpiresAt = jwtTokenService.GetTokenExpiration(accessToken),
            User = new UserInfoDto
            {
                Id = user.Id,
                UserName = user.UserName,
                Email = user.Email,
                FullName = user.FullName,
                AvatarUrl = user.AvatarUrl,
                Role = user.Role.ToString()
            }
        });
    }
}



