using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.Tags.Commands;

/// <summary>
/// Tag silme komutu
/// </summary>
public record DeleteTagCommand(Guid Id) : IRequest<Result>;

public class DeleteTagCommandHandler : IRequestHandler<DeleteTagCommand, Result>
{
    private readonly IUnitOfWork _unitOfWork;

    public DeleteTagCommandHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<Result> Handle(DeleteTagCommand request, CancellationToken cancellationToken)
    {
        var tag = await _unitOfWork.Tags.GetByIdAsync(request.Id, cancellationToken);

        if (tag is null)
            return Result.Failure("Tag not found");

        // Soft delete
        tag.IsDeleted = true;
        tag.UpdatedAt = DateTime.UtcNow;

        _unitOfWork.Tags.Update(tag);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result.Success();
    }
}

