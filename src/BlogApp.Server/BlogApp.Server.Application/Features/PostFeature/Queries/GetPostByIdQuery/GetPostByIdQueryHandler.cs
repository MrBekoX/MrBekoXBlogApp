using AutoMapper;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryHandler(
    IUnitOfWork unitOfWork,
    IMapper mapper) : IRequestHandler<GetPostByIdQueryRequest, GetPostByIdQueryResponse>
{
    public async Task<GetPostByIdQueryResponse> Handle(GetPostByIdQueryRequest request, CancellationToken cancellationToken)
    {
        var post = await unitOfWork.PostsRead.Query()
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .Include(p => p.Comments)
            .AsSplitQuery() // Prevents Cartesian explosion with multiple collection includes (Tags, Comments)
            .Where(p => p.Id == request.Id && !p.IsDeleted)
            .FirstOrDefaultAsync(cancellationToken);

        if (post is null)
        {
            return new GetPostByIdQueryResponse
            {
                Result = Result<PostDetailQueryDto>.Failure(PostBusinessRuleMessages.PostNotFound(request.Id))
            };
        }

        var dto = mapper.Map<PostDetailQueryDto>(post);

        return new GetPostByIdQueryResponse
        {
            Result = Result<PostDetailQueryDto>.Success(dto)
        };
    }
}



