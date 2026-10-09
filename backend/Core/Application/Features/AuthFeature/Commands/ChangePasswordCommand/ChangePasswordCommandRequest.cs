using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Commands.ChangePasswordCommand;

public class ChangePasswordCommandRequest : IRequest<Result<Unit>>
{
    public ChangePasswordDto Dto { get; init; } = default!;
    public Guid UserId { get; init; }
}
