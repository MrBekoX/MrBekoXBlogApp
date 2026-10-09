using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AuthFeature.Rules;

public interface IAuthBusinessRules
{
    Task<Result> CheckEmailIsUniqueAsync(string email);
    Task<Result> CheckUserNameIsUniqueAsync(string userName);
}

