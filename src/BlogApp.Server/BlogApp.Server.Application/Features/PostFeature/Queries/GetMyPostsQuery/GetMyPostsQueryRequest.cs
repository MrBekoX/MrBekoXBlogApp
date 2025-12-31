using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;

public class GetMyPostsQueryRequest : IRequest<GetMyPostsQueryResponse>
{
    public Guid UserId { get; init; }
    public int PageNumber { get; init; } = 1;
    public int PageSize { get; init; } = 10;
}

