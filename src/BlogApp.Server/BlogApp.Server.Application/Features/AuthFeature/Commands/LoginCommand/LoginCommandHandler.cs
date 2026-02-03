using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
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
            // Fix Race Condition: Use transaction to prevent concurrent login attempts
            using var transaction = await unitOfWork.BeginTransactionAsync(System.Data.IsolationLevel.Serializable, cancellationToken);
            
            try
            {
                // Başarısız giriş sayısını thread-safe (atomik) olarak artır
                await unitOfWork.UsersWrite.IncrementFailedLoginAttemptsAsync(user.Id, cancellationToken);
                
                // Transaction içinde kullanıcıyı yeniden çek (Race condition önlemi)
                var updatedUser = await unitOfWork.UsersRead.GetByIdAsync(user.Id, cancellationToken);
                
                if (updatedUser != null)
                {
                    if (updatedUser.FailedLoginAttempts >= MaxFailedAttempts)
                    {
                        // Hesabı kilitle
                        updatedUser.LockoutEndTime = DateTime.UtcNow.Add(LockoutDuration);
                        updatedUser.FailedLoginAttempts = 0;
                        await unitOfWork.UsersWrite.UpdateAsync(updatedUser, cancellationToken);
                    }
                }
                
                await unitOfWork.SaveChangesAsync(cancellationToken);
                await transaction.CommitAsync(cancellationToken);
            }
            catch
            {
                await transaction.RollbackAsync(cancellationToken);
                throw;
            }

            // Güncel durumu kontrol et
            var finalUser = await unitOfWork.UsersRead.GetByIdAsync(user.Id, cancellationToken);
            if (finalUser?.LockoutEndTime > DateTime.UtcNow)
            {
                var remainingMinutes = (int)Math.Ceiling((finalUser.LockoutEndTime.Value - DateTime.UtcNow).TotalMinutes);
                return new LoginCommandResponse
                {
                    Result = Result<AuthResponseDto>.Failure(AuthBusinessRuleMessages.AccountLockedWithTime(remainingMinutes))
                };
            }

            // Not: IncrementFailedLoginAttemptsAsync zaten veritabanına yazdığı için tekrar Update/Save çağırmaya gerek yok

            var currentAttempts = finalUser?.FailedLoginAttempts ?? 0;
            var remainingAttempts = MaxFailedAttempts - currentAttempts;
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



