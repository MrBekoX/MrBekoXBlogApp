using BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;
using BlogApp.Server.Application.Features.AuthFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.AuthFeature.Validators;

public class RefreshTokenCommandRequestValidator : AbstractValidator<RefreshTokenCommandRequest>
{
    public RefreshTokenCommandRequestValidator()
    {
        RuleFor(x => x.RefreshTokenCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.RefreshTokenCommandRequestDto != null, () =>
        {
            RuleFor(x => x.RefreshTokenCommandRequestDto!.RefreshToken)
                .NotEmpty().WithMessage(AuthValidationMessages.RefreshTokenRequired);
        });
    }
}
