using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Constants;

namespace BlogApp.Server.Application.Features.AuthFeature.Rules;

public class AuthBusinessRules : IAuthBusinessRules
{
    private readonly IUnitOfWork _unitOfWork;

    public AuthBusinessRules(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<Result> CheckEmailIsUniqueAsync(string email)
    {
        var exists = await _unitOfWork.UsersRead.ExistsAsync(
            u => u.Email.ToLower() == email.ToLower());

        return exists
            ? Result.Failure(AuthBusinessRuleMessages.EmailAlreadyExists)
            : Result.Success();
    }

    public async Task<Result> CheckUserNameIsUniqueAsync(string userName)
    {
        var exists = await _unitOfWork.UsersRead.ExistsAsync(
            u => u.UserName.ToLower() == userName.ToLower());

        return exists
            ? Result.Failure(AuthBusinessRuleMessages.UserNameAlreadyExists)
            : Result.Success();
    }
}