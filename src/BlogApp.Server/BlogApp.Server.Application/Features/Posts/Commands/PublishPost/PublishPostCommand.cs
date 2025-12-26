using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.PublishPost;

/// <summary>
/// Blog yazısı yayınlama komutu
/// </summary>
public record PublishPostCommand(Guid Id) : IRequest<Result>;

/// <summary>
/// Blog yazısı yayından kaldırma komutu
/// </summary>
public record UnpublishPostCommand(Guid Id) : IRequest<Result>;
