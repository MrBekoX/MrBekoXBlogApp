using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;
using BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;
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
    [ProducesResponseType(typeof(ApiResponse<IEnumerable<GetAllTagQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetTags()
    {
        var response = await Mediator.Send(new GetAllTagQueryRequest());

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<IEnumerable<GetAllTagQueryDto>>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<IEnumerable<GetAllTagQueryDto>>.SuccessResult(response.Result.Value!));
    }

    /// <summary>
    /// Create a new tag
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,Editor")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateTag([FromBody] CreateTagCommandDto dto)
    {
        var response = await Mediator.Send(new CreateTagCommandRequest
        {
            CreateTagCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

        return CreatedAtAction(
            nameof(GetTags),
            ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Tag created successfully"));
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
        var response = await Mediator.Send(new DeleteTagCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

        return NoContent();
    }
}
