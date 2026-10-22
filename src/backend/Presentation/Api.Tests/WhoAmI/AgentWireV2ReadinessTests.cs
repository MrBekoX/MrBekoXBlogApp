using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Infrastructure.Messaging;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// K4 üretici bariyeri: v2 yalnız AgentWireV2:Enabled + broker hazırlığı ile seçilir; hazırlık
/// sonucu 30 sn önbelleklenir, hata "hazır değil" sayılır (fail-closed). Broker gerektirmez:
/// hazırlık sahte, zaman TimeProvider ile kontrol edilir.
/// </summary>
public sealed class AgentWireV2ReadinessTests
{
    private sealed class FakeReadiness(bool ready, bool throws = false) : IAgentWireV2Readiness
    {
        public int Calls { get; private set; }

        public Task<bool> IsReadyAsync(CancellationToken cancellationToken = default)
        {
            Calls++;
            return throws ? throw new InvalidOperationException("broker yok") : Task.FromResult(ready);
        }
    }

    private sealed class ManualTimeProvider(DateTimeOffset start) : TimeProvider
    {
        public DateTimeOffset Now { get; set; } = start;

        public override DateTimeOffset GetUtcNow() => Now;
    }

    private static AgentWireVersionSelector Selector(bool enabled, IAgentWireV2Readiness readiness) =>
        new(Options.Create(new AgentWireV2Settings { Enabled = enabled }), readiness);

    [Fact]
    public async Task Disabled_Flag_Selects_V1_Without_Probing()
    {
        var readiness = new FakeReadiness(ready: true);

        Assert.Equal(1, await Selector(enabled: false, readiness).SelectAsync());
        Assert.Equal(0, readiness.Calls);
    }

    [Fact]
    public async Task Enabled_And_Ready_Selects_V2()
    {
        Assert.Equal(2, await Selector(enabled: true, new FakeReadiness(ready: true)).SelectAsync());
    }

    [Fact]
    public async Task Enabled_But_Not_Ready_Falls_Back_To_V1()
    {
        Assert.Equal(1, await Selector(enabled: true, new FakeReadiness(ready: false)).SelectAsync());
    }

    [Fact]
    public async Task Readiness_Failure_Falls_Back_To_V1()
    {
        Assert.Equal(1, await Selector(enabled: true, new FakeReadiness(ready: true, throws: true)).SelectAsync());
    }

    [Fact]
    public void Default_Settings_Keep_Feature_Off()
    {
        var settings = new AgentWireV2Settings();
        Assert.False(settings.Enabled);
        Assert.Equal(30, settings.ReadinessCacheSeconds);
    }

    [Fact]
    public async Task Cache_Reuses_Result_For_Ttl_Then_Probes_Again()
    {
        var time = new ManualTimeProvider(new DateTimeOffset(2026, 10, 22, 9, 0, 0, TimeSpan.Zero));
        var cache = new AgentReadinessCache(TimeSpan.FromSeconds(30), time);
        var probes = 0;
        var answer = false;
        Task<bool> Probe(CancellationToken _) { probes++; return Task.FromResult(answer); }

        Assert.False(await cache.GetAsync(Probe));
        answer = true;
        time.Now = time.Now.AddSeconds(29);
        Assert.False(await cache.GetAsync(Probe)); // önbellekte: hâlâ hazır değil
        Assert.Equal(1, probes);

        time.Now = time.Now.AddSeconds(2);
        Assert.True(await cache.GetAsync(Probe)); // süre doldu: yeniden probe
        Assert.Equal(2, probes);
    }

    [Fact]
    public async Task Cache_Treats_Probe_Exception_As_Not_Ready_And_Caches_It()
    {
        var time = new ManualTimeProvider(DateTimeOffset.UnixEpoch);
        var cache = new AgentReadinessCache(TimeSpan.FromSeconds(30), time);
        var probes = 0;
        Task<bool> Probe(CancellationToken _) { probes++; throw new InvalidOperationException("kuyruk yok"); }

        Assert.False(await cache.GetAsync(Probe));
        Assert.False(await cache.GetAsync(Probe));
        Assert.Equal(1, probes);
    }
}
