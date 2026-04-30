using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.ChangePasswordCommand;

public class ChangePasswordCommandHandler(
    IUnitOfWork unitOfWork,
    ITokenBlacklistService tokenBlacklist) : IRequestHandler<ChangePasswordCommandRequest, ChangePasswordCommandResponse>
{
    public async Task<ChangePasswordCommandResponse> Handle(ChangePasswordCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.Dto;

        var user = await unitOfWork.UsersRead.GetByIdAsync(request.UserId, cancellationToken);
        if (user is null || user.IsDeleted)
        {
            return new ChangePasswordCommandResponse
            {
                Result = Result.Failure(AuthBusinessRuleMessages.UserNotFound)
            };
        }

        bool currentPasswordValid;
        try
        {
            currentPasswordValid = BCrypt.Net.BCrypt.Verify(dto.CurrentPassword, user.PasswordHash);
        }
        catch
        {
            currentPasswordValid = false;
        }

        if (!currentPasswordValid)
        {
            return new ChangePasswordCommandResponse
            {
                Result = Result.Failure("Current password is incorrect.")
            };
        }

        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.NewPassword, workFactor: 12);
        await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);

        // Revoke all refresh tokens (force re-login on all devices)
        await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(user.Id, cancellationToken);

        // Invalidate all access tokens for this user via Redis blacklist
        await tokenBlacklist.InvalidateAllUserTokensAsync(user.Id, cancellationToken);

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new ChangePasswordCommandResponse { Result = Result.Success() };
    }
}
