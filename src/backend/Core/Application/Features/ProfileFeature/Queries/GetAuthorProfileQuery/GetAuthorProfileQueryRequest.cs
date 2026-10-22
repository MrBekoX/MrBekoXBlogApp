using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.ProfileFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileQuery;

/// <summary>Aktif public profil sorgusu. ICacheableQuery DEĞİLDİR: her istek aktif sürüm/public
/// politikasını yeniden uygular (eski gövde cache'ten sunulmaz; K6/A37).</summary>
public sealed record GetAuthorProfileQueryRequest : IRequest<Result<AuthorProfileDto>>;
