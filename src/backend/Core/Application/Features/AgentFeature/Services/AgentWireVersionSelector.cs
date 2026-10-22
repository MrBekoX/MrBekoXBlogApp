using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Microsoft.Extensions.Options;

namespace BlogApp.Core.Application.Features.AgentFeature.Services;

/// <summary>Yeni bir run'ın wire sürümünü kabul anında seçer (K4); sürüm run boyunca değişmez.</summary>
public interface IAgentWireVersionSelector
{
    Task<int> SelectAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// v2 yalnız <c>AgentWireV2:Enabled</c> açık VE <see cref="IAgentWireV2Readiness"/> hazırken seçilir;
/// aksi halde v1 (eski akış). Hazırlık sorgusu hatası v1'e düşer (fail-closed).
/// </summary>
public sealed class AgentWireVersionSelector(
    IOptions<AgentWireV2Settings> options,
    IAgentWireV2Readiness readiness) : IAgentWireVersionSelector
{
    public async Task<int> SelectAsync(CancellationToken cancellationToken = default)
    {
        if (!options.Value.Enabled)
        {
            return AgentMessageTypeRegistry.V1;
        }

        try
        {
            return await readiness.IsReadyAsync(cancellationToken)
                ? AgentMessageTypeRegistry.V2
                : AgentMessageTypeRegistry.V1;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            return AgentMessageTypeRegistry.V1;
        }
    }
}
