using FluentValidation;

namespace BlogApp.Server.Application.Features.Posts.Commands.UpdatePost;

/// <summary>
/// UpdatePostCommand validator
/// </summary>
public class UpdatePostCommandValidator : AbstractValidator<UpdatePostCommand>
{
    public UpdatePostCommandValidator()
    {
        RuleFor(x => x.Id)
            .NotEmpty().WithMessage("Post ID is required");

        RuleFor(x => x.Title)
            .NotEmpty().WithMessage("Title is required")
            .MaximumLength(200).WithMessage("Title cannot exceed 200 characters");

        RuleFor(x => x.Content)
            .NotEmpty().WithMessage("Content is required")
            .MinimumLength(10).WithMessage("Content must be at least 10 characters");

        RuleFor(x => x.Excerpt)
            .MaximumLength(500).WithMessage("Excerpt cannot exceed 500 characters")
            .When(x => !string.IsNullOrEmpty(x.Excerpt));

        RuleFor(x => x.MetaTitle)
            .MaximumLength(70).WithMessage("Meta title cannot exceed 70 characters")
            .When(x => !string.IsNullOrEmpty(x.MetaTitle));

        RuleFor(x => x.MetaDescription)
            .MaximumLength(160).WithMessage("Meta description cannot exceed 160 characters")
            .When(x => !string.IsNullOrEmpty(x.MetaDescription));
    }
}
