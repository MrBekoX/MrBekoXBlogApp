using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.ChangePasswordCommand;

public class ChangePasswordCommandRequest : IRequest<Result<Unit>>
{
    public ChangePasswordDto Dto { get; init; } = default!;
    public Guid UserId { get; init; }
}
