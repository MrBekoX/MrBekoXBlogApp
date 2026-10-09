using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.Constants;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.LoginCommand;

public class LoginCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService,
    ILogger<LoginCommandHandler> logger) : IRequestHandler<LoginCommandRequest, Result<AuthResponseDto>>
{
    private const int MaxFailedAttempts = 5;
    private static readonly TimeSpan LockoutDuration = TimeSpan.FromMinutes(15);

    public async Task<Result<AuthResponseDto>> Handle(LoginCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.LoginCommandRequestDto!;

        // Kullanıcıyı bul
        var user = await unitOfWork.UsersRead.GetSingleAsync(
            u => u.Email.ToLower() == dto.Email.ToLower() && !u.IsDeleted,
            cancellationToken);

        if (user is null)
        {
            // Dummy BCrypt verify to equalize timing (prevents email enumeration via timing)
            BCrypt.Net.BCrypt.Verify("dummy-password", "$2a$11$K4GByMz0K3mFQoOBdVcHj.ZGZxYKYfblvP9OhNt7E.XzMnH4x1AEK");
            return Result<AuthResponseDto>.Failure(Error.Unauthorized(AuthBusinessRuleMessages.InvalidCredentials));
        }

        // Hesap kilitli mi kontrol et
        if (user.LockoutEndTime.HasValue && user.LockoutEndTime > DateTime.UtcNow)
        {
            var remainingMinutes = (int)(user.LockoutEndTime.Value - DateTime.UtcNow).TotalMinutes + 1;
            return Result<AuthResponseDto>.Failure(Error.Domain(AuthBusinessRuleMessages.AccountLockedWithTime(remainingMinutes)));
        }

        // Güvenli şifre doğrulama (BCrypt)
        bool passwordValid;
        try
        {
            passwordValid = BCrypt.Net.BCrypt.Verify(dto.Password, user.PasswordHash);
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "BCrypt verification failed for user {UserId}", user.Id);
            passwordValid = false;
        }

        if (!passwordValid)
        {
            // Atomik SQL UPDATE ile başarısız giriş sayısını artır (ExecuteUpdateAsync)
            await unitOfWork.UsersWrite.IncrementFailedLoginAttemptsAsync(user.Id, cancellationToken);

            // Güncel durumu kontrol et
            var updatedUser = await unitOfWork.UsersRead.GetByIdAsync(user.Id, cancellationToken);

            if (updatedUser != null && updatedUser.FailedLoginAttempts >= MaxFailedAttempts)
            {
                // Hesabı kilitle
                updatedUser.LockoutEndTime = DateTime.UtcNow.Add(LockoutDuration);
                updatedUser.FailedLoginAttempts = 0;
                await unitOfWork.UsersWrite.UpdateAsync(updatedUser, cancellationToken);
                await unitOfWork.SaveChangesAsync(cancellationToken);
            }

            var finalUser = updatedUser;
            if (finalUser?.LockoutEndTime > DateTime.UtcNow)
            {
                var remainingMinutes = (int)Math.Ceiling((finalUser.LockoutEndTime.Value - DateTime.UtcNow).TotalMinutes);
                return Result<AuthResponseDto>.Failure(Error.Domain(AuthBusinessRuleMessages.AccountLockedWithTime(remainingMinutes)));
            }

            // Not: IncrementFailedLoginAttemptsAsync zaten veritabanına yazdığı için tekrar Update/Save çağırmaya gerek yok

            return Result<AuthResponseDto>.Failure(Error.Unauthorized(AuthBusinessRuleMessages.InvalidCredentials));
        }

        // Kullanıcı aktif mi?
        if (!user.IsActive)
        {
            return Result<AuthResponseDto>.Failure(Error.Forbidden(AuthBusinessRuleMessages.AccountDisabled));
        }

        // Başarılı giriş - lockout bilgilerini sıfırla
        user.FailedLoginAttempts = 0;
        user.LockoutEndTime = null;

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

        // Son giriş zamanını güncelle
        user.LastLoginAt = DateTime.UtcNow;
        await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);

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



