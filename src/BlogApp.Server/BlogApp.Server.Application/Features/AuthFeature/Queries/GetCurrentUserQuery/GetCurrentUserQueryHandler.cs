using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetCurrentUserQueryRequest, GetCurrentUserQueryResponse>
{
    public async Task<GetCurrentUserQueryResponse> Handle(GetCurrentUserQueryRequest request, CancellationToken cancellationToken)
    {
        var user = await unitOfWork.UsersRead.GetByIdAsync(request.UserId, cancellationToken);

        if (user is null)
        {
            return new GetCurrentUserQueryResponse
            {
                Result = Result<UserInfoDto>.Failure("User not found")
            };
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

        return new GetCurrentUserQueryResponse
        {
            Result = Result<UserInfoDto>.Success(userInfo)
        };
    }
}
