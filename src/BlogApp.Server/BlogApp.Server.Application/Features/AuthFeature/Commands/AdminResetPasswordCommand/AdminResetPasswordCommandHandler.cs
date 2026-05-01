using BlogApp.Server.Application.Common.Errors;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;

public class AdminResetPasswordCommandHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<AdminResetPasswordCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(AdminResetPasswordCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.Dto;

        var user = await unitOfWork.UsersRead.GetByIdAsync(dto.UserId, cancellationToken);
        if (user is null || user.IsDeleted)
        {
            return Result<Unit>.Failure(Error.NotFound(AuthBusinessRuleMessages.UserNotFound));
        }

        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.NewPassword, workFactor: 12);
        user.FailedLoginAttempts = 0;
        user.LockoutEndTime = null;
        await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);

        // Revoke all refresh tokens
        await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(user.Id, cancellationToken);

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<Unit>.Success(Unit.Value);
    }
}
