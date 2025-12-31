using BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.CategoryFeature.Validators;

public class UpdateCategoryCommandRequestValidator : AbstractValidator<UpdateCategoryCommandRequest>
{
    public UpdateCategoryCommandRequestValidator()
    {
        RuleFor(x => x.UpdateCategoryCommandRequestDto)
            .NotNull()
            .WithMessage("Request data is required");

        When(x => x.UpdateCategoryCommandRequestDto != null, () =>
        {
            RuleFor(x => x.UpdateCategoryCommandRequestDto!.Id)
                .NotEmpty()
                .WithMessage(CategoryValidationMessages.IdRequired)
                .WithErrorCode(CategoryValidationMessages.IdRequiredCode);

            RuleFor(x => x.UpdateCategoryCommandRequestDto!.Name)
                .NotEmpty()
                .WithMessage(CategoryValidationMessages.NameRequired)
                .WithErrorCode(CategoryValidationMessages.NameRequiredCode)
                .MinimumLength(CategoryValidationMessages.NameMinLength)
                .WithMessage(CategoryValidationMessages.NameTooShort)
                .WithErrorCode(CategoryValidationMessages.NameTooShortCode)
                .MaximumLength(CategoryValidationMessages.NameMaxLength)
                .WithMessage(CategoryValidationMessages.NameTooLong)
                .WithErrorCode(CategoryValidationMessages.NameTooLongCode);

            RuleFor(x => x.UpdateCategoryCommandRequestDto!.Description)
                .MaximumLength(CategoryValidationMessages.DescriptionMaxLength)
                .WithMessage(CategoryValidationMessages.DescriptionTooLong)
                .WithErrorCode(CategoryValidationMessages.DescriptionTooLongCode)
                .When(x => x.UpdateCategoryCommandRequestDto!.Description != null);
        });
    }
}

