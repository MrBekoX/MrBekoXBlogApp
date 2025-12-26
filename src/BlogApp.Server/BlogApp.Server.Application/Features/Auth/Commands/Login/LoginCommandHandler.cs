using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Auth;
using BlogApp.Server.Domain.Entities;
using MediatR;

namespace BlogApp.Server.Application.Features.Auth.Commands.Login;

/// <summary>
/// LoginCommand handler
/// </summary>
public class LoginCommandHandler : IRequestHandler<LoginCommand, Result<AuthResponseDto>>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly IJwtTokenService _jwtTokenService;

    public LoginCommandHandler(IUnitOfWork unitOfWork, IJwtTokenService jwtTokenService)
    {
        _unitOfWork = unitOfWork;
        _jwtTokenService = jwtTokenService;
    }

    private const int MaxFailedAttempts = 5;
    private static readonly TimeSpan LockoutDuration = TimeSpan.FromMinutes(15);

    public async Task<Result<AuthResponseDto>> Handle(LoginCommand request, CancellationToken cancellationToken)
    {
        // Kullanıcıyı bul
        var user = await _unitOfWork.Users.GetAsync(
            u => u.Email.ToLower() == request.Email.ToLower() && !u.IsDeleted,
            cancellationToken);

        if (user is null)
            return Result<AuthResponseDto>.Failure("Invalid email or password");

        // Hesap kilitli mi kontrol et
        if (user.LockoutEndTime.HasValue && user.LockoutEndTime > DateTime.UtcNow)
        {
            var remainingMinutes = (int)(user.LockoutEndTime.Value - DateTime.UtcNow).TotalMinutes + 1;
            return Result<AuthResponseDto>.Failure($"Account is locked. Try again in {remainingMinutes} minutes.");
        }

        // GÜVENLİK DÜZELTMESİ: Güvenli şifre doğrulama (BCrypt)
        // Şifreler veritabanında asla düz metin olarak saklanmaz, hashlenerek saklanır.
        if (!BCrypt.Net.BCrypt.Verify(request.Password, user.PasswordHash))
        {
            // Başarısız giriş sayısını artır
            user.FailedLoginAttempts++;
            
            if (user.FailedLoginAttempts >= MaxFailedAttempts)
            {
                // GÜVENLİK DÜZELTMESİ: Brute Force (Kaba Kuvvet) saldırılarına karşı koruma.
                // Belirli sayıda başarısız denemeden sonra hesabı geçici olarak kilitle.
                // Hesabı kilitle
                user.LockoutEndTime = DateTime.UtcNow.Add(LockoutDuration);
                user.FailedLoginAttempts = 0;
                _unitOfWork.Users.Update(user);
                await _unitOfWork.SaveChangesAsync(cancellationToken);
                return Result<AuthResponseDto>.Failure($"Too many failed attempts. Account locked for {LockoutDuration.TotalMinutes} minutes.");
            }
            
            _unitOfWork.Users.Update(user);
            await _unitOfWork.SaveChangesAsync(cancellationToken);
            
            var remainingAttempts = MaxFailedAttempts - user.FailedLoginAttempts;
            return Result<AuthResponseDto>.Failure($"Invalid email or password. {remainingAttempts} attempts remaining.");
        }

        // Kullanıcı aktif mi?
        if (!user.IsActive)
            return Result<AuthResponseDto>.Failure("Account is disabled");

        // Başarılı giriş - lockout bilgilerini sıfırla
        user.FailedLoginAttempts = 0;
        user.LockoutEndTime = null;

        // Token oluştur
        var accessToken = _jwtTokenService.GenerateAccessToken(user);
        var refreshToken = _jwtTokenService.GenerateRefreshToken();

        // Refresh token kaydet
        var refreshTokenEntity = new Domain.Entities.RefreshToken
        {
            Id = Guid.NewGuid(),
            Token = refreshToken,
            UserId = user.Id,
            ExpiresAt = DateTime.UtcNow.AddDays(7),
            CreatedAt = DateTime.UtcNow,
            CreatedByIp = request.IpAddress
        };

        await _unitOfWork.RefreshTokens.AddAsync(refreshTokenEntity, cancellationToken);

        // Son giriş zamanını güncelle
        user.LastLoginAt = DateTime.UtcNow;
        _unitOfWork.Users.Update(user);

        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<AuthResponseDto>.Success(new AuthResponseDto
        {
            AccessToken = accessToken,
            RefreshToken = refreshToken,
            ExpiresAt = _jwtTokenService.GetTokenExpiration(accessToken),
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
