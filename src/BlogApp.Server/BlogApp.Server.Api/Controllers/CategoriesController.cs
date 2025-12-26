using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.DTOs.Categories;
using BlogApp.Server.Application.Features.Categories.Commands;
using BlogApp.Server.Application.Features.Categories.Queries;
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
    [ProducesResponseType(typeof(ApiResponse<List<CategoryDetailDto>>), StatusCodes.Status200OK)]
    public async Task<IActionResult> GetCategories([FromQuery] bool includeInactive = false)
    {
        var result = await Mediator.Send(new GetCategoriesQuery { IncludeInactive = includeInactive });

        return Ok(ApiResponse<List<CategoryDetailDto>>.SuccessResult(result));
    }

    /// <summary>
    /// Get category by ID
    /// </summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType(typeof(ApiResponse<CategoryDetailDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetCategory(Guid id)
    {
        var result = await Mediator.Send(new GetCategoryByIdQuery(id));

        if (result is null)
            return NotFound(ApiResponse<CategoryDetailDto>.FailureResult("Category not found"));

        return Ok(ApiResponse<CategoryDetailDto>.SuccessResult(result));
    }

    /// <summary>
    /// Create a new category
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(typeof(ApiResponse<Guid>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateCategory([FromBody] CreateCategoryCommand command)
    {
        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<Guid>.FailureResult(result.Error!));

        return CreatedAtAction(
            nameof(GetCategories),
            ApiResponse<Guid>.SuccessResult(result.Value, "Category created successfully"));
    }

    /// <summary>
    /// Update a category
    /// </summary>
    [HttpPut("{id:guid}")]
    [Authorize(Roles = "Admin")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> UpdateCategory(Guid id, [FromBody] UpdateCategoryCommand command)
    {
        // Set the ID from the URL
        command = command with { Id = id };

        var result = await Mediator.Send(command);

        if (result.IsFailure)
            return BadRequest(ApiResponse<object>.FailureResult(result.Error!));

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
        var result = await Mediator.Send(new DeleteCategoryCommand(id));

        if (result.IsFailure)
            return NotFound(ApiResponse<object>.FailureResult(result.Error!));

        return NoContent();
    }
}
