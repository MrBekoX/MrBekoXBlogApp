using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AuthFeature.Rules;

public interface IAuthBusinessRules
{
    Task<Result> CheckEmailIsUniqueAsync(string email);
    Task<Result> CheckUserNameIsUniqueAsync(string userName);
}
