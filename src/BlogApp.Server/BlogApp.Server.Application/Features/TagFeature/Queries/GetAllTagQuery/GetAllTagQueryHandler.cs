using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;

public class GetAllTagQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetAllTagQueryRequest, GetAllTagQueryResponse>
{
    public async Task<GetAllTagQueryResponse> Handle(GetAllTagQueryRequest request, CancellationToken cancellationToken)
    {
        var tags = await unitOfWork.Tags.Query()
            .AsNoTracking()
            .Include(t => t.Posts)
            .Where(t => !t.IsDeleted)
            .OrderBy(t => t.Name)
            .Select(t => new GetAllTagQueryDto
            {
                Id = t.Id,
                Name = t.Name,
                Slug = t.Slug,
                PostCount = t.Posts.Count(p => !p.IsDeleted),
                CreatedAt = t.CreatedAt
            })
            .ToListAsync(cancellationToken);

        return new GetAllTagQueryResponse
        {
            Result = Result<IEnumerable<GetAllTagQueryDto>>.Success(tags)
        };
    }
}
