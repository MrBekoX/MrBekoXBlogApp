using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Auth;
using MediatR;

namespace BlogApp.Server.Application.Features.Auth.Commands.Login;

/// <summary>
/// Kullanıcı giriş komutu
/// </summary>
public record LoginCommand : IRequest<Result<AuthResponseDto>>
{
    public string Email { get; init; } = default!;
    public string Password { get; init; } = default!;
    public string? IpAddress { get; init; }
}
