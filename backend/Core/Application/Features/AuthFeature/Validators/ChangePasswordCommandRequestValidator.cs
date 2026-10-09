using BlogApp.Core.Application.Features.AuthFeature.Commands.ChangePasswordCommand;
using BlogApp.Core.Application.Features.AuthFeature.Constants;
using FluentValidation;

namespace BlogApp.Core.Application.Features.AuthFeature.Validators;

public class ChangePasswordCommandRequestValidator : AbstractValidator<ChangePasswordCommandRequest>
{
    public ChangePasswordCommandRequestValidator()
    {
        RuleFor(x => x.Dto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.Dto != null, () =>
        {
            RuleFor(x => x.Dto!.CurrentPassword)
                .NotEmpty().WithMessage("Current password is required");

            RuleFor(x => x.Dto!.NewPassword)
                .NotEmpty().WithMessage(AuthValidationMessages.PasswordRequired)
                .MinimumLength(8).WithMessage(AuthValidationMessages.PasswordMinLength)
                .MaximumLength(128).WithMessage("Password must not exceed 128 characters")
                .Matches(@"[A-Z]").WithMessage(AuthValidationMessages.PasswordRequiresUppercase)
                .Matches(@"[a-z]").WithMessage(AuthValidationMessages.PasswordRequiresLowercase)
                .Matches(@"[0-9]").WithMessage(AuthValidationMessages.PasswordRequiresDigit)
                .Matches(@"[!@#$%^&*(),.?""':{}|<>_\-\[\]\\\/`~+=;]").WithMessage(AuthValidationMessages.PasswordRequiresSpecialChar);

            RuleFor(x => x.Dto!.ConfirmNewPassword)
                .NotEmpty().WithMessage(AuthValidationMessages.ConfirmPasswordRequired)
                .Equal(x => x.Dto!.NewPassword).WithMessage(AuthValidationMessages.PasswordsDoNotMatch);
        });
    }
}
