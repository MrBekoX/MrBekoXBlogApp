using System.Reflection;
using BlogApp.Core.Application.Common.Behaviors;
using BlogApp.Core.Application.Features.AuthFeature.Rules;
using BlogApp.Core.Application.Features.CategoryFeature.Rules;
using BlogApp.Core.Application.Features.PostFeature.Rules;
using BlogApp.Core.Application.Features.TagFeature.Rules;
using FluentValidation;
using MediatR;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Core.Application;

/// <summary>
/// Application katmanı dependency injection
/// </summary>
public static class DependencyInjection
{
    public static IServiceCollection AddApplicationServices(this IServiceCollection services)
    {
        var assembly = Assembly.GetExecutingAssembly();

        // MediatR
        services.AddMediatR(cfg =>
        {
            cfg.RegisterServicesFromAssembly(assembly);
        });

        // FluentValidation
        services.AddValidatorsFromAssembly(assembly);

        // AutoMapper
        services.AddAutoMapper(cfg => cfg.AddMaps(assembly), assembly);

        // Pipeline Behaviors
        // Pipeline Behaviors (sıralama önemli: dıştan içe)
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(LoggingBehavior<,>));
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(CachingBehavior<,>));
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(IdempotencyBehavior<,>));

        // Business Rules
        services.AddScoped<ICategoryBusinessRules, CategoryBusinessRules>();
        services.AddScoped<ITagBusinessRules, TagBusinessRules>();
        services.AddScoped<IPostBusinessRules, PostBusinessRules>();
        services.AddScoped<IAuthBusinessRules, AuthBusinessRules>();

        return services;
    }
}

