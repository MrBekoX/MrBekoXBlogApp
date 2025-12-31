using BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.AuthFeature.Validators;

public class LoginCommandRequestValidator : AbstractValidator<LoginCommandRequest>
{
    public LoginCommandRequestValidator()
    {
        RuleFor(x => x.LoginCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.LoginCommandRequestDto != null, () =>
        {
            RuleFor(x => x.LoginCommandRequestDto!.Email)
                .NotEmpty().WithMessage(AuthValidationMessages.EmailRequired)
                .EmailAddress().WithMessage(AuthValidationMessages.EmailInvalid);

            RuleFor(x => x.LoginCommandRequestDto!.Password)
                .NotEmpty().WithMessage(AuthValidationMessages.PasswordRequired);
        });
    }
}

