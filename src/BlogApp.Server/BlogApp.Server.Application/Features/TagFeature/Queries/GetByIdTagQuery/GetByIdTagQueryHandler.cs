using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetByIdTagQueryRequest, GetByIdTagQueryResponse>
{
    public async Task<GetByIdTagQueryResponse> Handle(GetByIdTagQueryRequest request, CancellationToken cancellationToken)
    {
        var tag = await unitOfWork.TagsRead.GetSingleAsync(t => t.Id == request.Id && !t.IsDeleted, cancellationToken);

        if (tag is null || tag.IsDeleted)
        {
            return new GetByIdTagQueryResponse
            {
                Result = Result<GetByIdTagQueryDto>.Failure(TagBusinessRuleMessages.TagNotFoundGeneric)
            };
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

        return new GetByIdTagQueryResponse
        {
            Result = Result<GetByIdTagQueryDto>.Success(dto)
        };
    }
}



