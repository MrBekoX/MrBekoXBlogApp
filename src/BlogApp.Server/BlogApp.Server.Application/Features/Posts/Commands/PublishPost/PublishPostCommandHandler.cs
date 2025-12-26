using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Exceptions;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.PublishPost;

/// <summary>
/// PublishPostCommand handler
/// </summary>
public class PublishPostCommandHandler : IRequestHandler<PublishPostCommand, Result>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICacheService _cacheService;

    public PublishPostCommandHandler(IUnitOfWork unitOfWork, ICacheService cacheService)
    {
        _unitOfWork = unitOfWork;
        _cacheService = cacheService;
    }

    public async Task<Result> Handle(PublishPostCommand request, CancellationToken cancellationToken)
    {
        var post = await _unitOfWork.Posts.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
            throw new NotFoundException(nameof(post), request.Id);

        post.Publish();

        _unitOfWork.Posts.Update(post);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        // Cache'i temizle (her iki format için de)
        await _cacheService.RemoveByPrefixAsync("posts:list", cancellationToken);
        await _cacheService.RemoveByPrefixAsync("posts-list", cancellationToken);

        return Result.Success();
    }
}

/// <summary>
/// UnpublishPostCommand handler
/// </summary>
public class UnpublishPostCommandHandler : IRequestHandler<UnpublishPostCommand, Result>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICacheService _cacheService;

    public UnpublishPostCommandHandler(IUnitOfWork unitOfWork, ICacheService cacheService)
    {
        _unitOfWork = unitOfWork;
        _cacheService = cacheService;
    }

    public async Task<Result> Handle(UnpublishPostCommand request, CancellationToken cancellationToken)
    {
        var post = await _unitOfWork.Posts.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
            throw new NotFoundException(nameof(post), request.Id);

        post.Unpublish();

        _unitOfWork.Posts.Update(post);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        // Cache'i temizle (her iki format için de)
        await _cacheService.RemoveByPrefixAsync("posts:list", cancellationToken);
        await _cacheService.RemoveByPrefixAsync("posts-list", cancellationToken);

        return Result.Success();
    }
}
