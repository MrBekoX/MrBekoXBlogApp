using AutoMapper;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
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
        var cacheKey = PostCacheKeys.BySlug(request.Slug);

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

        var post = await unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .AsSplitQuery()
            .Where(p => p.Slug == request.Slug && !p.IsDeleted && p.Status == PostStatus.Published)
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
        {
            return new GetPostBySlugQueryResponse
            {
                Result = Result<PostDetailQueryDto>.Failure(PostBusinessRuleMessages.PostNotFoundBySlug(request.Slug))
            };
        }

        // View count artır (atomic operation - race condition önlemi)
        // Not: ReadCommitted isolation level yeterli - view count için strict consistency gerekmez
        // Serializable deadlock ve performans sorunlarına yol açar
        if (request.IncrementViewCount)
        {
            try
            {
                // IncrementViewCountAsync uses atomic SQL UPDATE (SET view_count = view_count + 1)
                // which is inherently thread-safe without requiring Serializable isolation
                await unitOfWork.PostsWrite.IncrementViewCountAsync(post.Id, cancellationToken);
                await unitOfWork.SaveChangesAsync(cancellationToken);
            }
            catch
            {
                // View count increment failure should not break the page load
                // Log and continue - the page content is more important
            }
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



