using BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.CategoryFeature.Validators;

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

