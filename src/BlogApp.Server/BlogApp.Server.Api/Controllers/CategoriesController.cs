using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// Categories API controller
/// </summary>
public class CategoriesController : ApiControllerBase
{
    /// <summary>
    /// Get all categories
    /// </summary>
    [HttpGet]
    [ProducesResponseType(typeof(ApiResponse<IEnumerable<GetAllCategoryQueryDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetCategories([FromQuery] bool includeInactive = false)
    {
        var response = await Mediator.Send(new GetAllCategoryQueryRequest { IncludeInactive = includeInactive });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<IEnumerable<GetAllCategoryQueryDto>>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<IEnumerable<GetAllCategoryQueryDto>>.SuccessResult(response.Result.Value!));
    }

    /// <summary>
    /// Get category by ID
    /// </summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType(typeof(ApiResponse<GetByIdCategoryQueryDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetCategory(Guid id)
    {
        var response = await Mediator.Send(new GetByIdCategoryQueryRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<GetByIdCategoryQueryDto>.FailureResult(response.Result.Error!));

        return Ok(ApiResponse<GetByIdCategoryQueryDto>.SuccessResult(response.Result.Value!));
    }

    /// <summary>
    /// Create a new category
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateCategory([FromBody] CreateCategoryCommandDto dto)
    {
        var response = await Mediator.Send(new CreateCategoryCommandRequest
        {
            CreateCategoryCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

        return CreatedAtAction(
            nameof(GetCategories),
            ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Category created successfully"));
    }

    /// <summary>
    /// Update a category
    /// </summary>
    [HttpPut("{id:guid}")]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UpdateCategory(Guid id, [FromBody] UpdateCategoryCommandDto dto)
    {
        dto.Id = id;

        var response = await Mediator.Send(new UpdateCategoryCommandRequest
        {
            UpdateCategoryCommandRequestDto = dto
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<object>.FailureResult(response.Result.Error!));

        return NoContent();
    }

    /// <summary>
    /// Delete a category
    /// </summary>
    [HttpDelete("{id:guid}")]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteCategory(Guid id)
    {
        var response = await Mediator.Send(new DeleteCategoryCommandRequest { Id = id });

        if (!response.Result.IsSuccess)
            return NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

        return NoContent();
    }
}
