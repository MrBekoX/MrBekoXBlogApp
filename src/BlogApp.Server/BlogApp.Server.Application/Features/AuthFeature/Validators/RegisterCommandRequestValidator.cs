using BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.AuthFeature.Validators;

public class RegisterCommandRequestValidator : AbstractValidator<RegisterCommandRequest>
{
    public RegisterCommandRequestValidator()
    {
        RuleFor(x => x.RegisterCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.RegisterCommandRequestDto != null, () =>
        {
            RuleFor(x => x.RegisterCommandRequestDto!.UserName)
                .NotEmpty().WithMessage(AuthValidationMessages.UserNameRequired)
                .MinimumLength(3).WithMessage(AuthValidationMessages.UserNameMinLength)
                .MaximumLength(50).WithMessage(AuthValidationMessages.UserNameMaxLength)
                .Matches(@"^[a-zA-Z0-9_]+$").WithMessage("Username can only contain letters, numbers, and underscores");

            RuleFor(x => x.RegisterCommandRequestDto!.Email)
                .NotEmpty().WithMessage(AuthValidationMessages.EmailRequired)
                .EmailAddress().WithMessage(AuthValidationMessages.EmailInvalid)
                .MaximumLength(256).WithMessage("Email cannot exceed 256 characters");

            RuleFor(x => x.RegisterCommandRequestDto!.Password)
                .NotEmpty().WithMessage(AuthValidationMessages.PasswordRequired)
                .MinimumLength(8).WithMessage("Password must be at least 8 characters")
                .Matches(@"[A-Z]").WithMessage("Password must contain at least one uppercase letter")
                .Matches(@"[a-z]").WithMessage("Password must contain at least one lowercase letter")
                .Matches(@"[0-9]").WithMessage("Password must contain at least one number");

            RuleFor(x => x.RegisterCommandRequestDto!.ConfirmPassword)
                .NotEmpty().WithMessage(AuthValidationMessages.ConfirmPasswordRequired)
                .Equal(x => x.RegisterCommandRequestDto!.Password).WithMessage(AuthValidationMessages.PasswordsDoNotMatch);

            RuleFor(x => x.RegisterCommandRequestDto!.FirstName)
                .MaximumLength(50).WithMessage("First name cannot exceed 50 characters")
                .When(x => !string.IsNullOrEmpty(x.RegisterCommandRequestDto!.FirstName));

            RuleFor(x => x.RegisterCommandRequestDto!.LastName)
                .MaximumLength(50).WithMessage("Last name cannot exceed 50 characters")
                .When(x => !string.IsNullOrEmpty(x.RegisterCommandRequestDto!.LastName));
        });
    }
}
