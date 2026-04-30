using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;

public class AdminResetPasswordCommandHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<AdminResetPasswordCommandRequest, AdminResetPasswordCommandResponse>
{
    public async Task<AdminResetPasswordCommandResponse> Handle(AdminResetPasswordCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.Dto;

        var user = await unitOfWork.UsersRead.GetByIdAsync(dto.UserId, cancellationToken);
        if (user is null || user.IsDeleted)
        {
            return new AdminResetPasswordCommandResponse
            {
                Result = Result.Failure(AuthBusinessRuleMessages.UserNotFound)
            };
        }

        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.NewPassword, workFactor: 12);
        user.FailedLoginAttempts = 0;
        user.LockoutEndTime = null;
        await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);

        // Revoke all refresh tokens
        await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(user.Id, cancellationToken);

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new AdminResetPasswordCommandResponse { Result = Result.Success() };
    }
}
