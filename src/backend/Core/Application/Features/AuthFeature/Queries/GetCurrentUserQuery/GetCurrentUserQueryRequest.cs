using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryRequest : IRequest<Result<UserInfoDto>>
{
    public Guid UserId { get; set; }
}
