using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.DTOs.Tags;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.Tags.Queries;

/// <summary>
/// Tag listesi getirme sorgusu
/// </summary>
public record GetTagsQuery : IRequest<List<TagDetailDto>>;

public class GetTagsQueryHandler : IRequestHandler<GetTagsQuery, List<TagDetailDto>>
{
    private readonly IUnitOfWork _unitOfWork;

    public GetTagsQueryHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<List<TagDetailDto>> Handle(GetTagsQuery request, CancellationToken cancellationToken)
    {
        return await _unitOfWork.Tags.Query()
            .AsNoTracking()
            .Include(t => t.Posts)
            .Where(t => !t.IsDeleted)
            .OrderBy(t => t.Name)
            .Select(t => new TagDetailDto
            {
                Id = t.Id,
                Name = t.Name,
                Slug = t.Slug,
                PostCount = t.Posts.Count(p => !p.IsDeleted),
                CreatedAt = t.CreatedAt
            })
            .ToListAsync(cancellationToken);
    }
}
