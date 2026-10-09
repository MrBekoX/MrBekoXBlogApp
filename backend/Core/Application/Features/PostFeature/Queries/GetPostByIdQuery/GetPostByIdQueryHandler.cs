using AutoMapper;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.PostFeature.Constants;
using BlogApp.Core.Application.Features.PostFeature.DTOs;
using BlogApp.Core.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryHandler(
    IUnitOfWork unitOfWork,
    IMapper mapper) : IRequestHandler<GetPostByIdQueryRequest, Result<PostDetailQueryDto>>
{
    public async Task<Result<PostDetailQueryDto>> Handle(GetPostByIdQueryRequest request, CancellationToken cancellationToken)
    {
        var query = unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .AsSplitQuery()
            .Where(p => p.Id == request.Id && !p.IsDeleted);

        if (request.RequirePublishedStatus)
            query = query.Where(p => p.Status == PostStatus.Published);

        var post = await query.FirstOrDefaultAsync(cancellationToken);

        if (post is null)
        {
            return Result<PostDetailQueryDto>.Failure(Error.NotFound(PostBusinessRuleMessages.PostNotFound(request.Id)));
        }

        var dto = mapper.Map<PostDetailQueryDto>(post);

        return Result<PostDetailQueryDto>.Success(dto);
    }
}



