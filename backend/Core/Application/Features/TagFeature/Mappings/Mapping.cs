using AutoMapper;
using BlogApp.Core.Application.Features.TagFeature.DTOs;
using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Features.TagFeature.Mappings;

public class Mapping : Profile
{
    public Mapping()
    {
        CreateMap<Tag, CreateTagCommandDto>().ReverseMap();
        CreateMap<Tag, GetAllTagQueryDto>().ReverseMap();
        CreateMap<Tag, GetByIdTagQueryDto>().ReverseMap();
    }
}

