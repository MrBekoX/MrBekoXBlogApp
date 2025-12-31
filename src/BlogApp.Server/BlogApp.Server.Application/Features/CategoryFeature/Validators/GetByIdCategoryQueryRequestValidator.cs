using BlogApp.Server.Application.Features.CategoryFeature.Constants;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;
using FluentValidation;

namespace BlogApp.Server.Application.Features.CategoryFeature.Validators;

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

