using BlogApp.Core.Application.Common.Validators;
using BlogApp.Core.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using FluentValidation;

namespace BlogApp.Core.Application.Features.CategoryFeature.Validators;

public class CreateCategoryCommandRequestValidator : AbstractValidator<CreateCategoryCommandRequest>
{
    public CreateCategoryCommandRequestValidator()
    {
        RuleFor(x => x.CreateCategoryCommandRequestDto)
            .NotNull()
            .WithMessage("Request data is required");

        When(x => x.CreateCategoryCommandRequestDto != null, () =>
        {
            RuleFor(x => x.CreateCategoryCommandRequestDto!.Name)
                .NotEmpty()
                .WithMessage(CategoryValidationMessages.NameRequired)
                .WithErrorCode(CategoryValidationMessages.NameRequiredCode)
                .MinimumLength(CategoryValidationMessages.NameMinLength)
                .WithMessage(CategoryValidationMessages.NameTooShort)
                .WithErrorCode(CategoryValidationMessages.NameTooShortCode)
                .MaximumLength(CategoryValidationMessages.NameMaxLength)
                .WithMessage(CategoryValidationMessages.NameTooLong)
                .WithErrorCode(CategoryValidationMessages.NameTooLongCode);

            RuleFor(x => x.CreateCategoryCommandRequestDto!.Description)
                .MaximumLength(CategoryValidationMessages.DescriptionMaxLength)
                .WithMessage(CategoryValidationMessages.DescriptionTooLong)
                .WithErrorCode(CategoryValidationMessages.DescriptionTooLongCode)
                .When(x => x.CreateCategoryCommandRequestDto!.Description != null);

            RuleFor(x => x.CreateCategoryCommandRequestDto!.ImageUrl)
                .Must(url => string.IsNullOrEmpty(url) || UrlValidationHelper.BeAValidAndSafeUrl(url))
                .WithMessage("Gecersiz veya guvensiz URL.")
                .When(x => !string.IsNullOrEmpty(x.CreateCategoryCommandRequestDto!.ImageUrl));
        });
    }
}

