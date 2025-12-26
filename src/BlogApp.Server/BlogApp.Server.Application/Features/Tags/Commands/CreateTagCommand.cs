using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.ValueObjects;
using FluentValidation;
using MediatR;

namespace BlogApp.Server.Application.Features.Tags.Commands;

/// <summary>
/// Tag oluşturma komutu
/// </summary>
public record CreateTagCommand(string Name) : IRequest<Result<Guid>>;

public class CreateTagCommandValidator : AbstractValidator<CreateTagCommand>
{
    public CreateTagCommandValidator()
    {
        RuleFor(x => x.Name)
            .NotEmpty().WithMessage("Name is required")
            .MaximumLength(50).WithMessage("Name cannot exceed 50 characters");
    }
}

public class CreateTagCommandHandler : IRequestHandler<CreateTagCommand, Result<Guid>>
{
    private readonly IUnitOfWork _unitOfWork;

    public CreateTagCommandHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<Result<Guid>> Handle(CreateTagCommand request, CancellationToken cancellationToken)
    {
        var slug = Slug.CreateFromTitle(request.Name);

        var existingTag = await _unitOfWork.Tags.GetAsync(
            t => t.Slug == slug.Value, cancellationToken);

        if (existingTag is not null)
            return Result<Guid>.Failure("A tag with this name already exists");

        var tag = new Tag
        {
            Id = Guid.NewGuid(),
            Name = request.Name,
            Slug = slug.Value,
            CreatedAt = DateTime.UtcNow
        };

        await _unitOfWork.Tags.AddAsync(tag, cancellationToken);
        await _unitOfWork.SaveChangesAsync(cancellationToken);

        return Result<Guid>.Success(tag.Id);
    }
}
