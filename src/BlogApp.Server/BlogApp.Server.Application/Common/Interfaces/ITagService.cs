using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Service for managing tags with batch operations.
/// </summary>
public interface ITagService
{
    /// <summary>
    /// Gets existing tags or creates new ones for the given tag names.
    /// Uses batch query for better performance.
    /// </summary>
    /// <param name="tagNames">List of tag names</param>
    /// <param name="cancellationToken">Cancellation token</param>
    /// <returns>List of Tag entities (existing or newly created)</returns>
    Task<List<Tag>> GetOrCreateTagsAsync(IEnumerable<string> tagNames, CancellationToken cancellationToken = default);
}
