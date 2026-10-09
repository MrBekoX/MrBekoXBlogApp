using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Queries.GetAllTagQuery;

public class GetAllTagQueryRequest : IRequest<Result<IReadOnlyList<GetAllTagQueryDto>>>
{
    /// <summary>
    /// If true, includes tags with no published posts. Default is false.
    /// </summary>
    public bool IncludeEmpty { get; set; } = false;
}
