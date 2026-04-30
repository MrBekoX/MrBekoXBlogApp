using BlogApp.Server.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.AuthFeature.Validators;

public class AdminResetPasswordCommandRequestValidator : AbstractValidator<AdminResetPasswordCommandRequest>
{
    public AdminResetPasswordCommandRequestValidator()
    {
        RuleFor(x => x.Dto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.Dto != null, () =>
        {
            RuleFor(x => x.Dto!.UserId)
                .NotEmpty().WithMessage("User ID is required");

            RuleFor(x => x.Dto!.NewPassword)
                .NotEmpty().WithMessage(AuthValidationMessages.PasswordRequired)
                .MinimumLength(8).WithMessage(AuthValidationMessages.PasswordMinLength)
                .MaximumLength(128).WithMessage("Password must not exceed 128 characters")
                .Matches(@"[A-Z]").WithMessage(AuthValidationMessages.PasswordRequiresUppercase)
                .Matches(@"[a-z]").WithMessage(AuthValidationMessages.PasswordRequiresLowercase)
                .Matches(@"[0-9]").WithMessage(AuthValidationMessages.PasswordRequiresDigit)
                .Matches(@"[!@#$%^&*(),.?""':{}|<>_\-\[\]\\\/`~+=;]").WithMessage(AuthValidationMessages.PasswordRequiresSpecialChar);
        });
    }
}
