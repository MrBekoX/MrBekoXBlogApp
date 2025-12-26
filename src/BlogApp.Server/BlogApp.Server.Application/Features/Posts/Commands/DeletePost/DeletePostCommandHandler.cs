using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Exceptions;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.DeletePost;

/// <summary>
/// DeletePostCommand handler (Soft Delete)
/// </summary>
public class DeletePostCommandHandler : IRequestHandler<DeletePostCommand, Result>
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly ICurrentUserService _currentUserService;

    public DeletePostCommandHandler(IUnitOfWork unitOfWork, ICurrentUserService currentUserService)
    {
        _unitOfWork = unitOfWork;
        _currentUserService = currentUserService;
    }

    public async Task<Result> Handle(DeletePostCommand request, CancellationToken cancellationToken)
    {
        var post = await _unitOfWork.Posts.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
            throw new NotFoundException(nameof(post), request.Id);

        // Soft delete
        post.IsDeleted = true;
        post.DeletedAt = DateTime.UtcNow;
        post.UpdatedBy = _currentUserService.UserName;

        _unitOfWork.Posts.Update(post);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result.Success();
    }
}
