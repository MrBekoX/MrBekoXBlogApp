using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;

namespace BlogApp.Server.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryResponse
{
    public Result<UserInfoDto> Result { get; set; } = null!;
}
