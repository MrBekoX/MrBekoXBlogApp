using MediatR;

namespace BlogApp.Server.Application.Features.SeoFeature.Queries.GetSitemapQuery;

public class GetSitemapQueryRequest : IRequest<GetSitemapQueryResponse>
{
    public string BaseUrl { get; set; } = null!;
}
