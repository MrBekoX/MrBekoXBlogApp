using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;

public class GetAllTagQueryRequest : IRequest<GetAllTagQueryResponse>
{
    /// <summary>
    /// If true, includes tags with no published posts. Default is false.
    /// </summary>
    public bool IncludeEmpty { get; set; } = false;
}

