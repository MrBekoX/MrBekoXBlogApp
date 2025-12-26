using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Tags;
using BlogApp.Server.Application.Features.Tags.Commands;
using BlogApp.Server.Application.Features.Tags.Queries;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// Tags API controller
/// </summary>
public class TagsController : ApiControllerBase
{
    /// <summary>
    /// Get all tags
    /// </summary>
    [HttpGet]
    [ProducesResponseType(typeof(ApiResponse<List<TagDetailDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetTags()
    {
        var result = await Mediator.Send(new GetTagsQuery());

        return Ok(ApiResponse<List<TagDetailDto>>.SuccessResult(result));
    }

    /// <summary>
    /// Create a new tag
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateTag([FromBody] CreateTagCommand command)
    {
        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<Guid>.FailureResult(result.Error!));

        return CreatedAtAction(
            nameof(GetTags),
            ApiResponse<Guid>.SuccessResult(result.Value, "Tag created successfully"));
    }

    /// <summary>
    /// Delete a tag
    /// </summary>
    [HttpDelete("{id:guid}")]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteTag(Guid id)
    {
        var result = await Mediator.Send(new DeleteTagCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<object>.FailureResult(result.Error!));

        return NoContent();
    }
}
