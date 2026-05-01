using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryRequest : IRequest<Result<UserInfoDto>>
{
    public Guid UserId { get; set; }
}
