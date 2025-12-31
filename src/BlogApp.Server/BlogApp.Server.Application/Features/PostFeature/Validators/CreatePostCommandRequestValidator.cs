using BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.PostFeature.Validators;

public class CreatePostCommandRequestValidator : AbstractValidator<CreatePostCommandRequest>
{
    public CreatePostCommandRequestValidator()
    {
        RuleFor(x => x.CreatePostCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.CreatePostCommandRequestDto != null, () =>
        {
            RuleFor(x => x.CreatePostCommandRequestDto!.Title)
                .NotEmpty().WithMessage(PostValidationMessages.TitleRequired)
                .MinimumLength(3).WithMessage(PostValidationMessages.TitleMinLength)
                .MaximumLength(200).WithMessage(PostValidationMessages.TitleMaxLength);

            RuleFor(x => x.CreatePostCommandRequestDto!.Content)
                .NotEmpty().WithMessage(PostValidationMessages.ContentRequired)
                .MinimumLength(10).WithMessage(PostValidationMessages.ContentMinLength);

            RuleFor(x => x.CreatePostCommandRequestDto!.Excerpt)
                .MaximumLength(500).WithMessage(PostValidationMessages.ExcerptMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.Excerpt));

            RuleFor(x => x.CreatePostCommandRequestDto!.MetaTitle)
                .MaximumLength(70).WithMessage(PostValidationMessages.MetaTitleMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.MetaTitle));

            RuleFor(x => x.CreatePostCommandRequestDto!.MetaDescription)
                .MaximumLength(160).WithMessage(PostValidationMessages.MetaDescriptionMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.MetaDescription));

            RuleFor(x => x.CreatePostCommandRequestDto!.FeaturedImageUrl)
                .Must(BeAValidUrl).WithMessage("Featured image URL is not valid")
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.FeaturedImageUrl));
        });
    }

    private bool BeAValidUrl(string? url)
    {
        if (string.IsNullOrEmpty(url))
            return true;

        return Uri.TryCreate(url, UriKind.Absolute, out var uriResult)
               && (uriResult.Scheme == Uri.UriSchemeHttp || uriResult.Scheme == Uri.UriSchemeHttps);
    }
}

