namespace BlogApp.Core.Application.Common.Interfaces.Messaging;

/// <summary>
/// v2 üretici dağıtım bariyeri (K4): v2 komutlarının okunabileceği kanıtlanmadan v2 run üretilmez.
/// Infrastructure uygulaması broker'da <c>agent.execute.v2.q</c> ve <c>agent.control.v2.q</c>
/// kuyruklarını pasif bildirir; ikisi de var ve her birinde en az bir tüketici varsa hazırdır.
/// Sonuç kısa süre önbelleklenir; her hata "hazır değil" sayılır (fail-closed: v1'e düşülür,
/// who_am_i 503 alır).
/// </summary>
public interface IAgentWireV2Readiness
{
    Task<bool> IsReadyAsync(CancellationToken cancellationToken = default);
}
