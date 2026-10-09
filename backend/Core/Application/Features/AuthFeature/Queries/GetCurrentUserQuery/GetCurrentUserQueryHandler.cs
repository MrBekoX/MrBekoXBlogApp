using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetCurrentUserQueryRequest, Result<UserInfoDto>>
{
    public async Task<Result<UserInfoDto>> Handle(GetCurrentUserQueryRequest request, CancellationToken cancellationToken)
    {
        var user = await unitOfWork.UsersRead.GetByIdAsync(request.UserId, cancellationToken);

        if (user is null)
        {
            return Result<UserInfoDto>.Failure(Error.NotFound("User not found"));
        }

        var userInfo = new UserInfoDto
        {
            Id = user.Id,
            UserName = user.UserName,
            Email = user.Email,
            FullName = user.FullName,
            AvatarUrl = user.AvatarUrl,
            Role = user.Role.ToString()
        };

        return Result<UserInfoDto>.Success(userInfo);
    }
}
