using MediatR;

namespace BlogApp.Server.Application.Features.SeoFeature.Queries.GetRssFeedQuery;

public class GetRssFeedQueryRequest : IRequest<GetRssFeedQueryResponse>
{
    public string BaseUrl { get; set; } = null!;
}
