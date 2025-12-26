using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// API Controller base class
/// </summary>
[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public abstract class ApiControllerBase : ControllerBase
{
    private ISender? _mediator;

    protected ISender Mediator => _mediator ??= HttpContext.RequestServices.GetRequiredService<ISender>();
}
