using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.DeleteMediaCommand;

public class DeleteMediaCommandHandler(
    IFileStorageService fileStorageService) : IRequestHandler<DeleteMediaCommandRequest, DeleteMediaCommandResponse>
{
    public async Task<DeleteMediaCommandResponse> Handle(
        DeleteMediaCommandRequest request, CancellationToken cancellationToken)
    {
        if (string.IsNullOrEmpty(request.Url))
            return new DeleteMediaCommandResponse { Result = Result.Failure("URL is required") };

        var deleted = await fileStorageService.DeleteAsync(request.Url);

        return new DeleteMediaCommandResponse
        {
            Result = deleted ? Result.Success() : Result.Failure("File not found")
        };
    }
}
