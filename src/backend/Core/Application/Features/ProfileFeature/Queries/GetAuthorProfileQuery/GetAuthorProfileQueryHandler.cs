using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.ProfileFeature.Constants;
using BlogApp.Core.Application.Features.ProfileFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileQuery;

/// <summary>
/// Canonical profil gövdesi: yalnız manifest hash'i doğrulanmış, status=public ve approved profil
/// döner; aksi halde 503 (<see cref="ProfileErrorMessages.UnavailableCode"/>) — geri çekilmiş veya
/// bozuk profilin gövdesi asla sunulmaz.
/// </summary>
public sealed class GetAuthorProfileQueryHandler(IAuthorProfileSource profileSource)
    : IRequestHandler<GetAuthorProfileQueryRequest, Result<AuthorProfileDto>>
{
    public Task<Result<AuthorProfileDto>> Handle(GetAuthorProfileQueryRequest request, CancellationToken cancellationToken)
    {
        var state = profileSource.GetCurrent();
        return Task.FromResult(state.IsAvailable
            ? Result<AuthorProfileDto>.Success(AuthorProfileDto.From(state.Document!))
            : Result<AuthorProfileDto>.Failure(Error.Unavailable(ProfileErrorMessages.Unavailable, ProfileErrorMessages.UnavailableCode)));
    }
}
