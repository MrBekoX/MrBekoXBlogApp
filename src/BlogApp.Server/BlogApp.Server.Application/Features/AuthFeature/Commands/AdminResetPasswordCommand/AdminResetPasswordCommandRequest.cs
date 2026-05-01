using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;

public class AdminResetPasswordCommandRequest : IRequest<Result<Unit>>
{
    public AdminResetPasswordDto Dto { get; init; } = default!;
}
