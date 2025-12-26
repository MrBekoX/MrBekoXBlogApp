using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Auth;
using MediatR;

namespace BlogApp.Server.Application.Features.Auth.Commands.Register;

/// <summary>
/// Kullanıcı kayıt komutu
/// </summary>
public record RegisterCommand : IRequest<Result<AuthResponseDto>>
{
    public string UserName { get; init; } = default!;
    public string Email { get; init; } = default!;
    public string Password { get; init; } = default!;
    public string ConfirmPassword { get; init; } = default!;
    public string? FirstName { get; init; }
    public string? LastName { get; init; }
    public string? IpAddress { get; init; }
}
