using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.ProfileFeature.Constants;
using BlogApp.Core.Application.Features.ProfileFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileSnapshotQuery;

public sealed class GetAuthorProfileSnapshotQueryHandler(IAuthorProfileSource profileSource)
    : IRequestHandler<GetAuthorProfileSnapshotQueryRequest, Result<AuthorProfileSnapshotDto>>
{
    public Task<Result<AuthorProfileSnapshotDto>> Handle(GetAuthorProfileSnapshotQueryRequest request, CancellationToken cancellationToken)
    {
        var state = profileSource.GetCurrent();
        if (!state.IsAvailable)
        {
            return Task.FromResult(Result<AuthorProfileSnapshotDto>.Failure(
                Error.Unavailable(ProfileErrorMessages.Unavailable, ProfileErrorMessages.UnavailableCode)));
        }

        var document = state.Document!;
        return Task.FromResult(Result<AuthorProfileSnapshotDto>.Success(new AuthorProfileSnapshotDto(
            document.Snapshot.ProfileId,
            document.Snapshot.Revision,
            document.Snapshot.ContentHash,
            document.Status)));
    }
}
