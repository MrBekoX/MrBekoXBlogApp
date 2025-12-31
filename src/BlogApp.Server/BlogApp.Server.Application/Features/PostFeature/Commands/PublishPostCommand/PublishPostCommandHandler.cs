using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService) : IRequestHandler<PublishPostCommandRequest, PublishPostCommandResponse>
{
    public async Task<PublishPostCommandResponse> Handle(PublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        // 1. İş Kuralları Kontrolü
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new PublishPostCommandResponse { Result = Result.Failure(ruleResult.Error!) };
        }

        // 2. Postu Getir
        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return new PublishPostCommandResponse { Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric) };
        }

        // 3. Entity Metodunu Çağır
        // BlogPost.Publish() metodu hem Status'u "Published" yapar hem de PublishedAt'i "UtcNow" olarak ayarlar.
        post.Publish();

        // 4. Audit Bilgilerini Güncelle
        // Bu adım, EF Core'un entity üzerindeki değişikliği algılamasını (Change Tracking) garanti eder.
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        // 5. Kaydet
        await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // 6. Cache Temizle
        // Invalidate individual post caches (both by id and slug)
        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        // Rotate list cache version (all lists will be refreshed)
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        return new PublishPostCommandResponse { Result = Result.Success() };
    }
}

public class UnpublishPostCommandHandler(
    IUnitOfWork unitOfWork,
    ICacheService cacheService,
    IPostBusinessRules postBusinessRules,
    ICurrentUserService currentUserService) : IRequestHandler<UnpublishPostCommandRequest, UnpublishPostCommandResponse>
{
    public async Task<UnpublishPostCommandResponse> Handle(UnpublishPostCommandRequest request, CancellationToken cancellationToken)
    {
        // 1. İş Kuralları Kontrolü
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await postBusinessRules.CheckPostExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new UnpublishPostCommandResponse { Result = Result.Failure(ruleResult.Error!) };
        }

        // 2. Postu Getir
        var post = await unitOfWork.PostsRead.GetByIdAsync(request.Id, cancellationToken);
        if (post is null)
        {
            return new UnpublishPostCommandResponse { Result = Result.Failure(PostBusinessRuleMessages.PostNotFoundGeneric) };
        }

        // 3. Entity Metodunu Çağır
        // BlogPost.Unpublish() metodu Status'u "Draft" yapar ve PublishedAt'i "null"a çeker.
        post.Unpublish();

        // 4. Audit Bilgilerini Güncelle
        post.UpdatedAt = DateTime.UtcNow;
        post.UpdatedBy = currentUserService.UserName;

        // 5. Kaydet
        await unitOfWork.PostsWrite.UpdateAsync(post, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // 6. Cache Temizle
        await cacheService.RemoveAsync(PostCacheKeys.ById(post.Id), cancellationToken);
        await cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug), cancellationToken);
        await cacheService.RotateGroupVersionAsync(PostCacheKeys.ListGroup, cancellationToken);

        return new UnpublishPostCommandResponse { Result = Result.Success() };
    }
}


