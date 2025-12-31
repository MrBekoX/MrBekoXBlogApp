using AutoMapper;
using AutoMapper.QueryableExtensions;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;

public class GetMyPostsQueryHandler(
    IUnitOfWork unitOfWork,
    IMapper mapper) : IRequestHandler<GetMyPostsQueryRequest, GetMyPostsQueryResponse>
{
    public async Task<GetMyPostsQueryResponse> Handle(GetMyPostsQueryRequest request, CancellationToken cancellationToken)
    {
        var query = unitOfWork.PostsRead.GetAll()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Where(p => !p.IsDeleted && p.AuthorId == request.UserId)
            .OrderByDescending(p => p.CreatedAt);

        // Toplam sayı
        var totalCount = await query.CountAsync(cancellationToken);

        // Sayfalama ve DTO'ya dönüştürme (AutoMapper ProjectTo kullanarak)
        var posts = await query
            .Skip((request.PageNumber - 1) * request.PageSize)
            .Take(request.PageSize)
            .ProjectTo<PostListQueryDto>(mapper.ConfigurationProvider)
            .ToListAsync(cancellationToken);

        return new GetMyPostsQueryResponse
        {
            Result = new PaginatedList<PostListQueryDto>(posts, totalCount, request.PageNumber, request.PageSize)
        };
    }
}



