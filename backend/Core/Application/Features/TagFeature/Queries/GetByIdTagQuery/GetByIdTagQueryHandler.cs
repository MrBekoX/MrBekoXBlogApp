using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.TagFeature.Constants;
using BlogApp.Core.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetByIdTagQueryRequest, Result<GetByIdTagQueryDto>>
{
    public async Task<Result<GetByIdTagQueryDto>> Handle(GetByIdTagQueryRequest request, CancellationToken cancellationToken)
    {
        var tag = await unitOfWork.TagsRead.GetSingleAsync(t => t.Id == request.Id && !t.IsDeleted, cancellationToken);

        if (tag is null || tag.IsDeleted)
        {
            return Result<GetByIdTagQueryDto>.Failure(Error.NotFound(TagBusinessRuleMessages.TagNotFoundGeneric));
        }

        var dto = new GetByIdTagQueryDto
        {
            Id = tag.Id,
            Name = tag.Name,
            Slug = tag.Slug,
            PostCount = 0,
            CreatedAt = tag.CreatedAt,
            UpdatedAt = tag.UpdatedAt
        };

        return Result<GetByIdTagQueryDto>.Success(dto);
    }
}
