using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;

public class GetPostBySlugQueryRequest : IRequest<GetPostBySlugQueryResponse>
{
    public string Slug { get; set; } = default!;
    public bool IncrementViewCount { get; set; } = true;
}
