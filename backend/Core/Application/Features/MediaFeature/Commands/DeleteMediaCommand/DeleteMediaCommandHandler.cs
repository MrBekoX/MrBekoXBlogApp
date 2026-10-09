using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using MediatR;

namespace BlogApp.Core.Application.Features.MediaFeature.Commands.DeleteMediaCommand;

public class DeleteMediaCommandHandler(
    IFileStorageService fileStorageService) : IRequestHandler<DeleteMediaCommandRequest, Result<Unit>>
{
    public async Task<Result<Unit>> Handle(
        DeleteMediaCommandRequest request, CancellationToken cancellationToken)
    {
        if (string.IsNullOrEmpty(request.Url))
            return Result<Unit>.Failure(Error.Validation("URL is required"));

        var deleted = await fileStorageService.DeleteAsync(request.Url, cancellationToken).ConfigureAwait(false);

        if (!deleted)
            return Result<Unit>.Failure(Error.NotFound("File not found"));

        return Result<Unit>.Success(Unit.Value);
    }
}
