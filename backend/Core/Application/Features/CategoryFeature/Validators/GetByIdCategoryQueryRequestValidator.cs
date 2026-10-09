using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using BlogApp.Core.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;
using FluentValidation;

namespace BlogApp.Core.Application.Features.CategoryFeature.Validators;

public class GetByIdCategoryQueryRequestValidator : AbstractValidator<GetByIdCategoryQueryRequest>
{
    public GetByIdCategoryQueryRequestValidator()
    {
        RuleFor(x => x.Id)
            .NotEmpty()
            .WithMessage(CategoryValidationMessages.IdRequired)
            .WithErrorCode(CategoryValidationMessages.IdRequiredCode);
    }
}

