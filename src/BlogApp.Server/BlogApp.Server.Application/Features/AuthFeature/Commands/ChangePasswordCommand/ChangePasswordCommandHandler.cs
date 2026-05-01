using BlogApp.Server.Application.Common.Errors;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Commands.ChangePasswordCommand;

public class ChangePasswordCommandHandler(
    IUnitOfWork unitOfWork,
    ITokenBlacklistService tokenBlacklist) : IRequestHandler<ChangePasswordCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(ChangePasswordCommandRequest request, CancellationToken cancellationToken)
    {
        var dto = request.Dto;

        var user = await unitOfWork.UsersRead.GetByIdAsync(request.UserId, cancellationToken);
        if (user is null || user.IsDeleted)
        {
            return Result<Unit>.Failure(Error.NotFound(AuthBusinessRuleMessages.UserNotFound));
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
            return Result<Unit>.Failure(Error.Unauthorized("Current password is incorrect."));
        }

        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.NewPassword, workFactor: 12);
        await unitOfWork.UsersWrite.UpdateAsync(user, cancellationToken);

        // Revoke all refresh tokens (force re-login on all devices)
        await unitOfWork.RefreshTokensWrite.RevokeAllUserTokensAsync(user.Id, cancellationToken);

        // Invalidate all access tokens for this user via Redis blacklist
        await tokenBlacklist.InvalidateAllUserTokensAsync(user.Id, cancellationToken);

        await unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<Unit>.Success(Unit.Value);
    }
}
