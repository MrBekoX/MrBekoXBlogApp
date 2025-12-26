using BlogApp.Server.Application.Common.Models;
using MediatR;

namespace BlogApp.Server.Application.Features.Posts.Commands.DeletePost;

/// <summary>
/// Blog yazısı silme komutu
/// </summary>
public record DeletePostCommand(Guid Id) : IRequest<Result>;
