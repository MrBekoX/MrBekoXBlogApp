using System.Reflection;
using BlogApp.Server.Application.Common.Behaviors;
using BlogApp.Server.Application.Features.AuthFeature.Rules;
using BlogApp.Server.Application.Features.CategoryFeature.Rules;
using BlogApp.Server.Application.Features.PostFeature.Rules;
using BlogApp.Server.Application.Features.TagFeature.Rules;
using FluentValidation;
using MediatR;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Server.Application;

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
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(LoggingBehavior<,>));
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(CachingBehavior<,>));

        // Business Rules
        services.AddScoped<ICategoryBusinessRules, CategoryBusinessRules>();
        services.AddScoped<ITagBusinessRules, TagBusinessRules>();
        services.AddScoped<IPostBusinessRules, PostBusinessRules>();
        services.AddScoped<IAuthBusinessRules, AuthBusinessRules>();

        return services;
    }
}
