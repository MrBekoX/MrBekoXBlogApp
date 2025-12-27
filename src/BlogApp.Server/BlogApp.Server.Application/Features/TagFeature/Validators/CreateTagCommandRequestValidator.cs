using BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.TagFeature.Validators;

public class CreateTagCommandRequestValidator : AbstractValidator<CreateTagCommandRequest>
{
    public CreateTagCommandRequestValidator()
    {
        RuleFor(x => x.CreateTagCommandRequestDto)
            .NotNull()
            .WithMessage("Request data is required");

        When(x => x.CreateTagCommandRequestDto != null, () =>
        {
            RuleFor(x => x.CreateTagCommandRequestDto!.Name)
                .NotEmpty()
                .WithMessage(TagValidationMessages.NameRequired)
                .WithErrorCode(TagValidationMessages.NameRequiredCode)
                .MinimumLength(TagValidationMessages.NameMinLength)
                .WithMessage(TagValidationMessages.NameTooShort)
                .WithErrorCode(TagValidationMessages.NameTooShortCode)
                .MaximumLength(TagValidationMessages.NameMaxLength)
                .WithMessage(TagValidationMessages.NameTooLong)
                .WithErrorCode(TagValidationMessages.NameTooLongCode);
        });
    }
}
