using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;

public class LoginCommandHandler(
    IUnitOfWork unitOfWork,
    IJwtTokenService jwtTokenService) : IRequestHandler<LoginCommandRequest, LoginCommandResponse>
{
    private const int MaxFailedAttempts = 5;
    private static readonly TimeSpan LockoutDuration = TimeSpan.FromMinutes(15);

    public async Task<LoginCommandResponse> Handle(LoginCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.LoginCommandRequestDto!;

        // Kullanıcıyı bul
        var user = await unitOfWork.UsersRead.GetSingleAsync(
            u => u.Email.ToLower() == dto.Email.ToLower() && !u.IsDeleted,
            cancellationToken);

        if (user is null)
        {
            return new LoginCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.InvalidCredentials)
            };
        }

        // Hesap kilitli mi kontrol et
        if (user.LockoutEndTime.HasValue && user.LockoutEndTime > DateTime.UtcNow)
        {
            var remainingMinutes = (int)(user.LockoutEndTime.Value - DateTime.UtcNow).TotalMinutes + 1;
            return new LoginCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.AccountLockedWithTime(remainingMinutes))
            };
        }

        // Güvenli şifre doğrulama (BCrypt)
        if (!BCrypt.Net.BCrypt.Verify(dto.Password, user.PasswordHash))
        {
            // Başarısız giriş sayısını artır
            user.FailedLoginAttempts++;

            if (user.FailedLoginAttempts >= MaxFailedAttempts)
            {
                // Hesabı kilitle
                user.LockoutEndTime = DateTime.UtcNow.Add(LockoutDuration);
                user.FailedLoginAttempts = 0;
                await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);
                await unitOfWork.SaveChangesAsync(cancellationToken);
                return new LoginCommandResponse
                {
                    Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.TooManyAttempts((int)LockoutDuration.TotalMinutes))
                };
            }

            await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);
            await unitOfWork.SaveChangesAsync(cancellationToken);

            var remainingAttempts = MaxFailedAttempts - user.FailedLoginAttempts;
            return new LoginCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.RemainingAttempts(remainingAttempts))
            };
        }

        // Kullanıcı aktif mi?
        if (!user.IsActive)
        {
            return new LoginCommandResponse
            {
                Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.AccountDisabled)
            };
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

        return new LoginCommandResponse
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
