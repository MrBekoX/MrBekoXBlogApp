using BlogApp.Server.Application.Common.Validators;
using BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.PostFeature.Validators;

/// <summary>
/// Validator for SaveDraftCommandRequest - BUG-007 FIX
/// Ensures draft data is validated before saving to prevent invalid data entry.
/// </summary>
public class SaveDraftCommandRequestValidator : AbstractValidator<SaveDraftCommandRequest>
{
    public SaveDraftCommandRequestValidator()
    {
        RuleFor(x => x.SaveDraftCommandRequestDto)
            .NotNull().WithMessage(PostValidationMessages.DraftDataRequired);

        When(x => x.SaveDraftCommandRequestDto != null, () =>
        {
            // Draft için daha esnek kurallar - ama yine de validation gerekli
            RuleFor(x => x.SaveDraftCommandRequestDto!.Title)
                .NotEmpty().WithMessage(PostValidationMessages.TitleRequired)
                .MinimumLength(1).WithMessage(PostValidationMessages.TitleMinLength)
                .MaximumLength(200).WithMessage(PostValidationMessages.TitleMaxLength);

            RuleFor(x => x.SaveDraftCommandRequestDto!.Content)
                .NotEmpty().WithMessage(PostValidationMessages.ContentRequired)
                .MinimumLength(1).WithMessage(PostValidationMessages.ContentMinLength)
                .MaximumLength(500000).WithMessage(PostValidationMessages.ContentMaxLength);

            RuleFor(x => x.SaveDraftCommandRequestDto!.Excerpt)
                .MaximumLength(500).WithMessage(PostValidationMessages.ExcerptMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.Excerpt));

            RuleFor(x => x.SaveDraftCommandRequestDto!.MetaTitle)
                .MaximumLength(70).WithMessage(PostValidationMessages.MetaTitleMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.MetaTitle));

            RuleFor(x => x.SaveDraftCommandRequestDto!.MetaDescription)
                .MaximumLength(160).WithMessage(PostValidationMessages.MetaDescriptionMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.MetaDescription));

            RuleFor(x => x.SaveDraftCommandRequestDto!.FeaturedImageUrl)
                .Must(UrlValidationHelper.BeAValidAndSafeUrl).WithMessage(PostValidationMessages.FeaturedImageUrlInvalid)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.FeaturedImageUrl));

            // Tag validasyonu
            RuleForEach(x => x.SaveDraftCommandRequestDto!.TagNames)
                .MaximumLength(50).WithMessage(PostValidationMessages.TagNameMaxLength)
                .Matches(@"^[^<>""'&]+$").WithMessage(PostValidationMessages.TagNameInvalid)
                .When(x => x.SaveDraftCommandRequestDto!.TagNames != null && x.SaveDraftCommandRequestDto!.TagNames.Any());
        });
    }

}
