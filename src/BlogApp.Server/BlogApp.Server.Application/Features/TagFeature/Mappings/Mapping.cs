using AutoMapper;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Features.TagFeature.Mappings;

public class Mapping : Profile
{
    public Mapping()
    {
        CreateMap<Tag, CreateTagCommandDto>().ReverseMap();
        CreateMap<Tag, GetAllTagQueryDto>().ReverseMap();
        CreateMap<Tag, GetByIdTagQueryDto>().ReverseMap();
    }
}
