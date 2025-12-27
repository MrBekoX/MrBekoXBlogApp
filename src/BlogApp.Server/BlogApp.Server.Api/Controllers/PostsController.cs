using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;
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
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostListQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetPosts(
        [FromQuery] int pageNumber = 1,
        [FromQuery] int pageSize = 10,
        [FromQuery] string? searchTerm = null,
        [FromQuery] Guid? categoryId = null,
        [FromQuery] Guid? tagId = null,
        [FromQuery] Guid? authorId = null,
        [FromQuery] PostStatus? status = null,
        [FromQuery] bool? isFeatured = null,
        [FromQuery] string sortBy = "CreatedAt",
        [FromQuery] bool sortDescending = true)
    {
        var response = await Mediator.Send(new GetPostsListQueryRequest
        {
            PageNumber = pageNumber,
            PageSize = pageSize,
            SearchTerm = searchTerm,
            CategoryId = categoryId,
            TagId = tagId,
            AuthorId = authorId,
            Status = status,
            IsFeatured = isFeatured,
            SortBy = sortBy,
            SortDescending = sortDescending
        });

        return Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(
            response.Result,
            PaginationMeta.FromPaginatedList(response.Result)));
    }

    /// <summary>
    /// Get post by ID
    /// </summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetPost(Guid id)
    {
        var response = await Mediator.Send(new GetPostByIdQueryRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(response.Result.Value!));
    }

    /// <summary>
    /// Get post by slug
    /// </summary>
    [HttpGet("slug/{slug}")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetPostBySlug(string slug)
    {
        var response = await Mediator.Send(new GetPostBySlugQueryRequest { Slug = slug });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(response.Result.Value!));
    }

    /// <summary>
    /// Create a new post
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<IActionResult> CreatePost([FromBody] CreatePostCommandDto dto)
    {
        var response = await Mediator.Send(new CreatePostCommandRequest
        {
            CreatePostCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        // Oluşturulan postu getir
        var postResponse = await Mediator.Send(new GetPostByIdQueryRequest { Id = response.Result.Value });

        return CreatedAtAction(
            nameof(GetPost),
            new { id = response.Result.Value },
            ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value!, "Post created successfully"));
    }

    /// <summary>
    /// Update an existing post
    /// </summary>
    [HttpPut("{id:guid}")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UpdatePost(Guid id, [FromBody] UpdatePostCommandDto dto)
    {
        dto.Id = id;

        var response = await Mediator.Send(new UpdatePostCommandRequest
        {
            UpdatePostCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        // Güncellenen postu getir
        var postResponse = await Mediator.Send(new GetPostByIdQueryRequest { Id = id });

        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value!, "Post updated successfully"));
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
        var response = await Mediator.Send(new DeletePostCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

        return NoContent();
    }

    /// <summary>
    /// Publish a post
    /// </summary>
    [HttpPost("{id:guid}/publish")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> PublishPost(Guid id)
    {
        var response = await Mediator.Send(new PublishPostCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        var postResponse = await Mediator.Send(new GetPostByIdQueryRequest { Id = id });
        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value!, "Post published successfully"));
    }

    /// <summary>
    /// Unpublish a post
    /// </summary>
    [HttpPost("{id:guid}/unpublish")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UnpublishPost(Guid id)
    {
        var response = await Mediator.Send(new UnpublishPostCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        var postResponse = await Mediator.Send(new GetPostByIdQueryRequest { Id = id });
        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value!, "Post unpublished successfully"));
    }

    /// <summary>
    /// Archive a post
    /// </summary>
    [HttpPost("{id:guid}/archive")]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<PostDetailQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> ArchivePost(Guid id)
    {
        var response = await Mediator.Send(new UnpublishPostCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

        var postResponse = await Mediator.Send(new GetPostByIdQueryRequest { Id = id });
        return Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value!, "Post archived successfully"));
    }

    /// <summary>
    /// Get featured posts
    /// </summary>
    [HttpGet("featured")]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostListQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetFeaturedPosts([FromQuery] int pageSize = 5)
    {
        var response = await Mediator.Send(new GetPostsListQueryRequest
        {
            PageSize = pageSize,
            IsFeatured = true,
            Status = PostStatus.Published,
            SortDescending = true
        });

        return Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
    }

    /// <summary>
    /// Save draft (auto-save endpoint)
    /// </summary>
    [HttpPost("draft")]
    [HttpPut("draft")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> SaveDraft([FromBody] SaveDraftCommandDto dto)
    {
        var response = await Mediator.Send(new SaveDraftCommandRequest
        {
            SaveDraftCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved"));
    }

    /// <summary>
    /// Get user's drafts
    /// </summary>
    [HttpGet("drafts")]
    [Authorize(Roles = "Admin,Editor,Author")]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostListQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetDrafts([FromQuery] int page = 1, [FromQuery] int pageSize = 10)
    {
        var response = await Mediator.Send(new GetPostsListQueryRequest
        {
            PageNumber = page,
            PageSize = pageSize,
            Status = PostStatus.Draft,
            SortDescending = true
        });

        return Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
    }

    /// <summary>
    /// Get current user's posts
    /// </summary>
    [HttpGet("my")]
    [Authorize]
    [ProducesResponseType(typeof(ApiResponse<PaginatedList<PostListQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetMyPosts([FromQuery] int page = 1, [FromQuery] int pageSize = 10)
    {
        var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
        if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
            return Unauthorized(ApiResponse<PaginatedList<PostListQueryDto>>.FailureResult("User not authenticated"));

        var response = await Mediator.Send(new GetMyPostsQueryRequest
        {
            UserId = userId,
            PageNumber = page,
            PageSize = pageSize
        });

        return Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(
            response.Result,
            PaginationMeta.FromPaginatedList(response.Result)));
    }
}
