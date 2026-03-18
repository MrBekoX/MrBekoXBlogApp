using BlogApp.Server.Application.Common.Validators;
using BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.PostFeature.Validators;

public class UpdatePostCommandRequestValidator : AbstractValidator<UpdatePostCommandRequest>
{
    public UpdatePostCommandRequestValidator()
    {
        RuleFor(x => x.UpdatePostCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.UpdatePostCommandRequestDto != null, () =>
        {
            RuleFor(x => x.UpdatePostCommandRequestDto!.Id)
                .NotEmpty().WithMessage(PostValidationMessages.IdRequired);

            RuleFor(x => x.UpdatePostCommandRequestDto!.Title)
                .NotEmpty().WithMessage(PostValidationMessages.TitleRequired)
                .MinimumLength(3).WithMessage(PostValidationMessages.TitleMinLength)
                .MaximumLength(200).WithMessage(PostValidationMessages.TitleMaxLength);

            RuleFor(x => x.UpdatePostCommandRequestDto!.Content)
                .NotEmpty().WithMessage(PostValidationMessages.ContentRequired)
                .MinimumLength(10).WithMessage(PostValidationMessages.ContentMinLength)
                .MaximumLength(500000).WithMessage(PostValidationMessages.ContentMaxLength);

            RuleFor(x => x.UpdatePostCommandRequestDto!.Excerpt)
                .MaximumLength(500).WithMessage(PostValidationMessages.ExcerptMaxLength)
                .When(x => !string.IsNullOrEmpty(x.UpdatePostCommandRequestDto!.Excerpt));

            RuleFor(x => x.UpdatePostCommandRequestDto!.MetaTitle)
                .MaximumLength(70).WithMessage(PostValidationMessages.MetaTitleMaxLength)
                .When(x => !string.IsNullOrEmpty(x.UpdatePostCommandRequestDto!.MetaTitle));

            RuleFor(x => x.UpdatePostCommandRequestDto!.MetaDescription)
                .MaximumLength(160).WithMessage(PostValidationMessages.MetaDescriptionMaxLength)
                .When(x => !string.IsNullOrEmpty(x.UpdatePostCommandRequestDto!.MetaDescription));

            RuleFor(x => x.UpdatePostCommandRequestDto!.FeaturedImageUrl)
                .Must(UrlValidationHelper.BeAValidAndSafeUrl).WithMessage(PostValidationMessages.FeaturedImageUrlInvalid)
                .When(x => !string.IsNullOrEmpty(x.UpdatePostCommandRequestDto!.FeaturedImageUrl));

            // Tag validasyonu
            RuleForEach(x => x.UpdatePostCommandRequestDto!.TagNames)
                .MaximumLength(50).WithMessage(PostValidationMessages.TagNameMaxLength)
                .Matches(@"^[^<>""'&]+$").WithMessage(PostValidationMessages.TagNameInvalid)
                .When(x => x.UpdatePostCommandRequestDto!.TagNames != null && x.UpdatePostCommandRequestDto!.TagNames.Any());
        });
    }

}

