using BlogApp.Server.Application.Features.AdminFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.AdminFeature.Commands.GetQuarantineStatsCommand;

public record GetQuarantineStatsCommandRequest : IRequest<QuarantineStatsResponseDto>;

public record GetQuarantineStatsCommandResponse : QuarantineStatsResponseDto;
