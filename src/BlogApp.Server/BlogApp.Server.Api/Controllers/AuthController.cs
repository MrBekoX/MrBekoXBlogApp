using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;
using BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;
using BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// Authentication API controller
/// </summary>
public class AuthController : ApiControllerBase
{
    private readonly IWebHostEnvironment _environment;

    public AuthController(IWebHostEnvironment environment)
    {
        _environment = environment;
    }

    /// <summary>
    /// User login
    /// </summary>
    [HttpPost("login")]
    [ProducesResponseType(typeof(ApiResponse<AuthResponseWithCookiesDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> Login([FromBody] LoginCommandDto dto)
    {
        var response = await Mediator.Send(new LoginCommandRequest
        {
            LoginCommandRequestDto = new LoginCommandDto
            {
                Email = dto.Email,
                Password = dto.Password,
                IpAddress = GetIpAddress()
            }
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));

        // Set HttpOnly cookies
        SetAuthCookies(response.Result.Value!.AccessToken, response.Result.Value.RefreshToken, response.Result.Value.ExpiresAt);

        var result = new AuthResponseWithCookiesDto
        {
            ExpiresAt = response.Result.Value.ExpiresAt,
            User = response.Result.Value.User
        };

        return Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Login successful"));
    }

    /// <summary>
    /// User registration
    /// </summary>
    [HttpPost("register")]
    [ProducesResponseType(typeof(ApiResponse<AuthResponseWithCookiesDto>), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> Register([FromBody] RegisterCommandDto dto)
    {
        var response = await Mediator.Send(new RegisterCommandRequest
        {
            RegisterCommandRequestDto = new RegisterCommandDto
            {
                UserName = dto.UserName,
                Email = dto.Email,
                Password = dto.Password,
                ConfirmPassword = dto.ConfirmPassword,
                FirstName = dto.FirstName,
                LastName = dto.LastName,
                IpAddress = GetIpAddress()
            }
        });

        if (!response.Result.IsSuccess)
            return BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));

        // Set HttpOnly cookies
        SetAuthCookies(response.Result.Value!.AccessToken, response.Result.Value.RefreshToken, response.Result.Value.ExpiresAt);

        var result = new AuthResponseWithCookiesDto
        {
            ExpiresAt = response.Result.Value.ExpiresAt,
            User = response.Result.Value.User
        };

        return CreatedAtAction(
            nameof(Login),
            ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Registration successful"));
    }

    /// <summary>
    /// Refresh access token (reads refresh token from HttpOnly cookie)
    /// </summary>
    [HttpPost("refresh-token")]
    [ProducesResponseType(typeof(ApiResponse<AuthResponseWithCookiesDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> RefreshToken()
    {
        // Read refresh token from HttpOnly cookie
        var refreshToken = Request.Cookies["BlogApp.RefreshToken"];

        if (string.IsNullOrEmpty(refreshToken))
        {
            ClearAuthCookies();
            return BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Refresh token not found"));
        }

        var response = await Mediator.Send(new RefreshTokenCommandRequest
        {
            RefreshTokenCommandRequestDto = new RefreshTokenCommandDto
            {
                RefreshToken = refreshToken,
                IpAddress = GetIpAddress()
            }
        });

        if (!response.Result.IsSuccess)
        {
            ClearAuthCookies();
            return BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));
        }

        // Set new HttpOnly cookies
        SetAuthCookies(response.Result.Value!.AccessToken, response.Result.Value.RefreshToken, response.Result.Value.ExpiresAt);

        var result = new AuthResponseWithCookiesDto
        {
            ExpiresAt = response.Result.Value.ExpiresAt,
            User = response.Result.Value.User
        };

        return Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Token refreshed"));
    }

    /// <summary>
    /// Logout and clear auth cookies
    /// </summary>
    [HttpPost("logout")]
    [ProducesResponseType(typeof(ApiResponse<object>), StatusCodes.Status200OK)]
    public async Task<IActionResult> Logout([FromServices] IUnitOfWork unitOfWork)
    {
        var refreshToken = Request.Cookies["BlogApp.RefreshToken"];

        if (!string.IsNullOrEmpty(refreshToken))
        {
            // Revoke refresh token in database
            var storedToken = await unitOfWork.RefreshTokens.GetAsync(t => t.Token == refreshToken);

            if (storedToken != null)
            {
                storedToken.RevokedAt = DateTime.UtcNow;
                storedToken.RevokedByIp = GetIpAddress();
                storedToken.ReasonRevoked = "Logged out";
                unitOfWork.RefreshTokens.Update(storedToken);
                await unitOfWork.SaveChangesAsync();
            }
        }

        ClearAuthCookies();

        return Ok(ApiResponse<object>.SuccessResult(null, "Logged out successfully"));
    }

    /// <summary>
    /// Get current authenticated user
    /// </summary>
    [HttpGet("me")]
    [Authorize]
    [ProducesResponseType(typeof(ApiResponse<UserInfoDto>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<IActionResult> GetCurrentUser([FromServices] IUnitOfWork unitOfWork)
    {
        var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
        if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
            return Unauthorized(ApiResponse<UserInfoDto>.FailureResult("User not authenticated"));

        var user = await unitOfWork.Users.GetByIdAsync(userId);
        if (user is null)
            return NotFound(ApiResponse<UserInfoDto>.FailureResult("User not found"));

        var userInfo = new UserInfoDto
        {
            Id = user.Id,
            UserName = user.UserName,
            Email = user.Email,
            FullName = user.FullName,
            AvatarUrl = user.AvatarUrl,
            Role = user.Role.ToString()
        };

        return Ok(ApiResponse<UserInfoDto>.SuccessResult(userInfo));
    }

    private string? GetIpAddress()
    {
        if (Request.Headers.TryGetValue("X-Forwarded-For", out var forwardedFor))
            return forwardedFor.FirstOrDefault();

        return HttpContext.Connection.RemoteIpAddress?.MapToIPv4().ToString();
    }

    /// <summary>
    /// Sets HttpOnly cookies for access and refresh tokens
    /// </summary>
    private void SetAuthCookies(string accessToken, string refreshToken, DateTime accessTokenExpiry)
    {
        var isProduction = !_environment.IsDevelopment();

        // Access token cookie - expires with token
        var accessCookieOptions = new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api",
            Expires = accessTokenExpiry,
            IsEssential = true
        };

        // Refresh token cookie - longer expiry, restricted path
        var refreshCookieOptions = new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api/auth",
            Expires = DateTime.UtcNow.AddDays(7),
            IsEssential = true
        };

        Response.Cookies.Append("BlogApp.AccessToken", accessToken, accessCookieOptions);
        Response.Cookies.Append("BlogApp.RefreshToken", refreshToken, refreshCookieOptions);
    }

    /// <summary>
    /// Clears auth cookies
    /// </summary>
    private void ClearAuthCookies()
    {
        var isProduction = !_environment.IsDevelopment();

        Response.Cookies.Delete("BlogApp.AccessToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api"
        });

        Response.Cookies.Delete("BlogApp.RefreshToken", new CookieOptions
        {
            HttpOnly = true,
            Secure = isProduction,
            SameSite = SameSiteMode.Strict,
            Path = "/api/auth"
        });
    }
}
