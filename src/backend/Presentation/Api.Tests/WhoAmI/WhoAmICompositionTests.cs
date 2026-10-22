using System.Reflection;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Infrastructure;
using BlogApp.Infrastructure.Messaging;
using MediatR;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// Üretim DI kompozisyonu (Program.cs'teki agent kayıt sırası): kabul handler'ı wire seçici, profil
/// kaynağı ve geçmiş derleyicisini; sunum guard'ı profil kaynağı ve AgentWireV2 ayarını gerçekten
/// alır (opsiyonel parametreler null'a düşmez). Sağlayıcı kurulur ama DB/broker'a bağlanılmaz.
/// </summary>
public sealed class WhoAmICompositionTests
{
    private static ServiceProvider BuildProvider(bool wireV2Enabled)
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:DefaultConnection"] = "Host=127.0.0.1;Port=1;Database=composition;Username=x;Password=y",
                ["AgentWireV2:Enabled"] = wireV2Enabled ? "true" : "false",
            })
            .Build();

        var services = new ServiceCollection();
        services.AddLogging();
        services.AddHttpContextAccessor();
        services.AddSingleton<IConfiguration>(configuration);
        services.AddApplicationServices();
        services.AddInfrastructureServices(configuration);
        services.AddRabbitMqAgentMessaging(configuration);
        services.AddAgentOutbox(configuration);
        services.AddAgentEventProjection(configuration);
        services.AddAgentContentEvents(configuration);
        services.AddAgentCollaboration(configuration);
        services.AddAgentWireV2(configuration);
        return services.BuildServiceProvider();
    }

    private static object? CapturedField(object instance, Type fieldType) =>
        instance.GetType()
            .GetFields(BindingFlags.Instance | BindingFlags.NonPublic)
            .Single(f => f.FieldType == fieldType)
            .GetValue(instance);

    [Fact]
    public async Task Accept_Handler_Receives_WhoAmI_Dependencies()
    {
        await using var provider = BuildProvider(wireV2Enabled: true);
        await using var scope = provider.CreateAsyncScope();

        var handler = scope.ServiceProvider.GetRequiredService<IRequestHandler<AcceptAgentRunCommandRequest, Result<AgentRunAcceptedDto>>>();

        Assert.IsType<AcceptAgentRunCommandHandler>(handler);
        Assert.NotNull(CapturedField(handler, typeof(IAgentWireVersionSelector)));
        Assert.NotNull(CapturedField(handler, typeof(IAuthorProfileSource)));
        Assert.NotNull(CapturedField(handler, typeof(IAgentConversationHistoryComposer)));
    }

    [Fact]
    public async Task Presentation_Guard_Receives_Profile_Source_And_Wire_Settings()
    {
        await using var provider = BuildProvider(wireV2Enabled: true);
        await using var scope = provider.CreateAsyncScope();

        var guard = scope.ServiceProvider.GetRequiredService<IAgentResultPresentationGuard>();

        Assert.NotNull(CapturedField(guard, typeof(IAuthorProfileSource)));
        var options = (Microsoft.Extensions.Options.IOptions<BlogApp.Core.Application.Common.Options.AgentWireV2Settings>?)CapturedField(
            guard, typeof(Microsoft.Extensions.Options.IOptions<BlogApp.Core.Application.Common.Options.AgentWireV2Settings>));
        Assert.True(options!.Value.Enabled);
    }

    [Fact]
    public async Task Profile_Source_Reads_Packaged_Copy_And_Readiness_Is_Broker_Backed()
    {
        await using var provider = BuildProvider(wireV2Enabled: false);

        var source = provider.GetRequiredService<IAuthorProfileSource>();
        Assert.True(source.GetCurrent().IsAvailable);
        Assert.IsType<RabbitMqAgentWireV2Readiness>(
            provider.GetRequiredService<BlogApp.Core.Application.Common.Interfaces.Messaging.IAgentWireV2Readiness>());
    }
}
