using AutoMapper;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;

public class GetPostBySlugQueryHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IMapper mapper) : IRequestHandler<GetPostBySlugQueryRequest, GetPostBySlugQueryResponse>
{
    private static readonly TimeSpan CacheDuration = TimeSpan.FromMinutes(10);

    public async Task<GetPostBySlugQueryResponse> Handle(GetPostBySlugQueryRequest request, CancellationToken cancellationToken)
    {
        var cacheKey = $"post:slug:{request.Slug}";

        // View count artırılmayacaksa cache'den al
        if (!request.IncrementViewCount)
        {
            var cachedResult = await cacheService.GetAsync<PostDetailQueryDto>(cacheKey, cancellationToken);
            if (cachedResult != null)
            {
                return new GetPostBySlugQueryResponse
                {
                    Result = Result<PostDetailQueryDto>.Success(cachedResult)
                };
            }
        }

        var post = await unitOfWork.Posts.Query()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .Where(p => p.Slug == request.Slug && !p.IsDeleted && p.Status == PostStatus.Published)
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
        {
            return new GetPostBySlugQueryResponse
            {
                Result = Result<PostDetailQueryDto>.Failure(PostBusinessRuleMessages.PostNotFoundBySlug(request.Slug))
            };
        }

        // View count artır
        if (request.IncrementViewCount)
        {
            post.ViewCount++;
            unitOfWork.Posts.Update(post);
            await unitOfWork.SaveChangesAsync(cancellationToken);
        }

        var dto = mapper.Map<PostDetailQueryDto>(post);

        // Cache'e kaydet
        await cacheService.SetAsync(cacheKey, dto, CacheDuration, cancellationToken);

        return new GetPostBySlugQueryResponse
        {
            Result = Result<PostDetailQueryDto>.Success(dto)
        };
    }
}
