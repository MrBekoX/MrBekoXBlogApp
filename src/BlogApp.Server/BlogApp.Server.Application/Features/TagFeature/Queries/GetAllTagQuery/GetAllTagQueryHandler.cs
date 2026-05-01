using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;

public class GetAllTagQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetAllTagQueryRequest, Result<IReadOnlyList<GetAllTagQueryDto>>>
{
    public async Task<Result<IReadOnlyList<GetAllTagQueryDto>>> Handle(GetAllTagQueryRequest request, CancellationToken cancellationToken)
    {
        // Fix N+1 Query: Use projection without Include
        var query = unitOfWork.TagsRead.Query()
            .AsNoTracking()
            .Where(t => !t.IsDeleted);

        // Only filter by published posts if IncludeEmpty is false
        if (!request.IncludeEmpty)
        {
            query = query.Where(t => t.Posts.Any(p => !p.IsDeleted && p.Status == PostStatus.Published));
        }

        var tags = await query
            .OrderBy(t => t.Name)
            .Select(t => new GetAllTagQueryDto
            {
                Id = t.Id,
                Name = t.Name,
                Slug = t.Slug,
                // Fix N+1: Use subquery instead of loading Posts collection
                PostCount = t.Posts.Count(p => !p.IsDeleted && p.Status == PostStatus.Published),
                CreatedAt = t.CreatedAt
            })
            .ToListAsync(cancellationToken);

        return Result<IReadOnlyList<GetAllTagQueryDto>>.Success(tags);
    }
}
