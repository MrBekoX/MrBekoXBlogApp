using BlogApp.Core.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using FluentValidation;

namespace BlogApp.Core.Application.Features.CategoryFeature.Validators;

public class DeleteCategoryCommandRequestValidator : AbstractValidator<DeleteCategoryCommandRequest>
{
    public DeleteCategoryCommandRequestValidator()
    {
        RuleFor(x => x.Id)
            .NotEmpty()
            .WithMessage(CategoryValidationMessages.IdRequired)
            .WithErrorCode(CategoryValidationMessages.IdRequiredCode);
    }
}

