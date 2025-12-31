using BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.TagFeature.Validators;

public class DeleteTagCommandRequestValidator : AbstractValidator<DeleteTagCommandRequest>
{
    public DeleteTagCommandRequestValidator()
    {
        RuleFor(x => x.Id)
            .NotEmpty()
            .WithMessage(TagValidationMessages.IdRequired)
            .WithErrorCode(TagValidationMessages.IdRequiredCode);
    }
}

