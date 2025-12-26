using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Posts;
using BlogApp.Server.Application.Features.Posts.Commands.CreatePost;
using BlogApp.Server.Application.Features.Posts.Commands.DeletePost;
using BlogApp.Server.Application.Features.Posts.Commands.PublishPost;
using BlogApp.Server.Application.Features.Posts.Commands.SaveDraft;
using BlogApp.Server.Application.Features.Posts.Commands.UpdatePost;
using BlogApp.Server.Application.Features.Posts.Queries.GetPostById;
using BlogApp.Server.Application.Features.Posts.Queries.GetPostBySlug;
using BlogApp.Server.Application.Features.Posts.Queries.GetPostsList;
using BlogApp.Server.Application.Features.Posts.Queries.GetMyPosts;
using BlogApp.Server.Domain.Enums;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// Blog posts API controller
/// </summary>
public class PostsController : ApiControllerBase
{
    /// <summary>
    /// Get paginated list of posts
    /// </summary>
    [HttpGet]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetPosts([FromQuery] GetPostsListQuery query)
    {
        var result = await Mediator.Send(query);

        return Ok(ApiResponse<PaginatedList<PostDto>>.SuccessResult(
            result,
            PaginationMeta.FromPaginatedList(result)));
    }

    /// <summary>
    /// Get post by ID
    /// </summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetPost(Guid id)
    {
        var result = await Mediator.Send(new GetPostByIdQuery(id));

        if (result is null)
            return NotFound(ApiResponse<PostDetailDto>.FailureResult("Post not found"));

        return Ok(ApiResponse<PostDetailDto>.SuccessResult(result));
    }

    /// <summary>
    /// Get post by slug
    /// </summary>
    [HttpGet("slug/{slug}")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetPostBySlug(string slug)
    {
        var result = await Mediator.Send(new GetPostBySlugQuery(slug));

        if (result is null)
            return NotFound(ApiResponse<PostDetailDto>.FailureResult("Post not found"));

        return Ok(ApiResponse<PostDetailDto>.SuccessResult(result));
    }

    /// <summary>
    /// Create a new post
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<IActionResult> CreatePost([FromBody] CreatePostCommand command)
    {
        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<PostDetailDto>.FailureResult(result.Error!));

        // Oluşturulan postu getir
        var post = await Mediator.Send(new GetPostByIdQuery(result.Value));
        
        return CreatedAtAction(
            nameof(GetPost),
            new { id = result.Value },
            ApiResponse<PostDetailDto>.SuccessResult(post, "Post created successfully"));
    }

    /// <summary>
    /// Update an existing post
    /// </summary>
    [HttpPut("{id:guid}")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UpdatePost(Guid id, [FromBody] UpdatePostCommand command)
    {
        if (id != command.Id)
            return BadRequest(ApiResponse<PostDetailDto>.FailureResult("ID mismatch"));

        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<PostDetailDto>.FailureResult(result.Error!));

        // Güncellenen postu getir
        var post = await Mediator.Send(new GetPostByIdQuery(id));
        
        return Ok(ApiResponse<PostDetailDto>.SuccessResult(post, "Post updated successfully"));
    }

    /// <summary>
    /// Delete a post (soft delete)
    /// </summary>
    [HttpDelete("{id:guid}")]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeletePost(Guid id)
    {
        var result = await Mediator.Send(new DeletePostCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<object>.FailureResult(result.Error!));

        return NoContent();
    }

    /// <summary>
    /// Publish a post
    /// </summary>
    [HttpPost("{id:guid}/publish")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> PublishPost(Guid id)
    {
        var result = await Mediator.Send(new PublishPostCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<PostDetailDto>.FailureResult(result.Error!));

        var post = await Mediator.Send(new GetPostByIdQuery(id));
        return Ok(ApiResponse<PostDetailDto>.SuccessResult(post, "Post published successfully"));
    }

    /// <summary>
    /// Unpublish a post
    /// </summary>
    [HttpPost("{id:guid}/unpublish")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UnpublishPost(Guid id)
    {
        var result = await Mediator.Send(new UnpublishPostCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<PostDetailDto>.FailureResult(result.Error!));

        var post = await Mediator.Send(new GetPostByIdQuery(id));
        return Ok(ApiResponse<PostDetailDto>.SuccessResult(post, "Post unpublished successfully"));
    }

    /// <summary>
    /// Archive a post
    /// </summary>
    [HttpPost("{id:guid}/archive")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> ArchivePost(Guid id)
    {
        var result = await Mediator.Send(new UnpublishPostCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<PostDetailDto>.FailureResult(result.Error!));

        var post = await Mediator.Send(new GetPostByIdQuery(id));
        return Ok(ApiResponse<PostDetailDto>.SuccessResult(post, "Post archived successfully"));
    }

    /// <summary>
    /// Get featured posts
    /// </summary>
    [HttpGet("featured")]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetFeaturedPosts([FromQuery] int pageSize = 5)
    {
        var query = new GetPostsListQuery
        {
            PageSize = pageSize,
            IsFeatured = true,
            Status = PostStatus.Published,
            SortDescending = true
        };

        var result = await Mediator.Send(query);

        return Ok(ApiResponse<PaginatedList<PostDto>>.SuccessResult(result));
    }

    /// <summary>
    /// Save draft (auto-save endpoint)
    /// </summary>
    [HttpPost("draft")]
    [HttpPut("draft")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> SaveDraft([FromBody] SaveDraftCommand command)
    {
        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<Guid>.FailureResult(result.Error!));

        return Ok(ApiResponse<Guid>.SuccessResult(result.Value, "Draft saved"));
    }

    /// <summary>
    /// Get user's drafts
    /// </summary>
    [HttpGet("drafts")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetDrafts([FromQuery] int page = 1, [FromQuery] int pageSize = 10)
    {
        var query = new GetPostsListQuery
        {
            PageNumber = page,
            PageSize = pageSize,
            Status = PostStatus.Draft,
            SortDescending = true
        };

        var result = await Mediator.Send(query);

        return Ok(ApiResponse<PaginatedList<PostDto>>.SuccessResult(result));
    }

    /// <summary>
    /// Get current user's posts
    /// </summary>
    [HttpGet("my")]
    [Authorize]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetMyPosts([FromQuery] int page = 1, [FromQuery] int pageSize = 10)
    {
        var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
        if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
            return Unauthorized(ApiResponse<PaginatedList<PostDto>>.FailureResult("User not authenticated"));

        var query = new GetMyPostsQuery
        {
            UserId = userId,
            PageNumber = page,
            PageSize = pageSize
        };

        var result = await Mediator.Send(query);

        return Ok(ApiResponse<PaginatedList<PostDto>>.SuccessResult(
            result,
            PaginationMeta.FromPaginatedList(result)));
    }
}
