using BlogApp.Server.Application.Common.Validators;
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
                .MinimumLength(10).WithMessage(PostValidationMessages.ContentMinLength)
                .MaximumLength(500000).WithMessage(PostValidationMessages.ContentMaxLength);

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
                .Must(UrlValidationHelper.BeAValidAndSafeUrl).WithMessage(PostValidationMessages.FeaturedImageUrlInvalid)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.FeaturedImageUrl));

            // Tag validasyonu
            RuleForEach(x => x.CreatePostCommandRequestDto!.TagNames)
                .MaximumLength(50).WithMessage(PostValidationMessages.TagNameMaxLength)
                .Matches(@"^[^<>""'&]+$").WithMessage(PostValidationMessages.TagNameInvalid)
                .When(x => x.CreatePostCommandRequestDto!.TagNames != null && x.CreatePostCommandRequestDto!.TagNames.Any());
        });
    }

}

