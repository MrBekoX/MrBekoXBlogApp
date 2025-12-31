using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using BlogApp.Server.Application.Features.AuthFeature.Rules;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;

public class RegisterCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService,
    IAuthBusinessRules authBusinessRules) : IRequestHandler<RegisterCommandRequest, RegisterCommandResponse>
{
    public async Task<RegisterCommandResponse> Handle(RegisterCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.RegisterCommandRequestDto!;

        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await authBusinessRules.CheckEmailIsUniqueAsync(dto.Email),
            async () => await authBusinessRules.CheckUserNameIsUniqueAsync(dto.UserName)
        );

        if (!ruleResult.IsSuccess)
        {
            return new RegisterCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(ruleResult.Error!)
            };
        }

        // Kullanıcı oluştur
        var user = new User
        {
            Id = Guid.NewGuid(),
            UserName = dto.UserName,
            Email = dto.Email.ToLower(),
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.Password),
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

        return new RegisterCommandResponse
        {
            Result = Result<AuthResponseDto>.Success(new AuthResponseDto
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
            })
        };
    }
}



