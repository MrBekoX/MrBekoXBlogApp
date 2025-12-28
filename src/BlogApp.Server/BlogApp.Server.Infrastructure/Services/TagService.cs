using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.ValueObjects;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Service for managing tags with batch operations to prevent N+1 queries.
/// </summary>
public class TagService(IUnitOfWork unitOfWork) : ITagService
{
    public async Task<List<Tag>> GetOrCreateTagsAsync(IEnumerable<string> tagNames, CancellationToken cancellationToken = default)
    {
        var tagNameList = tagNames
            .Where(t => !string.IsNullOrWhiteSpace(t))
            .Select(t => t.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (tagNameList.Count == 0)
            return [];

        // Single batch query to get all existing tags
        var existingTags = await unitOfWork.TagsRead
            .GetWhere(t => tagNameList.Contains(t.Name))
            .ToListAsync(cancellationToken);

        var existingTagNames = existingTags
            .Select(t => t.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        // Create missing tags
        var newTags = new List<Tag>();
        foreach (var tagName in tagNameList.Where(name => !existingTagNames.Contains(name)))
        {
            var newTag = new Tag
            {
                Id = Guid.NewGuid(),
                Name = tagName,
                Slug = Slug.CreateFromTitle(tagName).Value,
                CreatedAt = DateTime.UtcNow
            };
            await unitOfWork.TagsWrite.AddAsync(newTag, cancellationToken);
            newTags.Add(newTag);
        }

        return [.. existingTags, .. newTags];
    }
}
