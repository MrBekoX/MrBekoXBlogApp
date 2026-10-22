using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.ProfileFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileSnapshotQuery;

/// <summary>Aktif profil sürüm metadatası (gövdesiz); backend/worker/about sürüm uyumsuzluğu
/// (drift) denetimi için.</summary>
public sealed record GetAuthorProfileSnapshotQueryRequest : IRequest<Result<AuthorProfileSnapshotDto>>;
