using AutoMapper;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Features.PostFeature.Mappings;

public class Mapping : Profile
{
    public Mapping()
    {
        // PostListQueryDto mapping - for list views
        CreateMap<BlogPost, PostListQueryDto>()
            .ForMember(dest => dest.Excerpt, opt => opt.MapFrom(src =>
                src.Excerpt ?? (src.Content.Length > 200 ? src.Content.Substring(0, 200) + "..." : src.Content)))
            .ForMember(dest => dest.Author, opt => opt.MapFrom(src => src.Author))
            .ForMember(dest => dest.Category, opt => opt.MapFrom(src => src.Category))
            .ForMember(dest => dest.Tags, opt => opt.MapFrom(src => src.Tags));

        // PostDetailQueryDto mapping - for detail views
        CreateMap<BlogPost, PostDetailQueryDto>()
            .ForMember(dest => dest.Author, opt => opt.MapFrom(src => src.Author))
            .ForMember(dest => dest.Category, opt => opt.MapFrom(src => src.Category))
            .ForMember(dest => dest.Tags, opt => opt.MapFrom(src => src.Tags))
            .ForMember(dest => dest.CommentCount, opt => opt.MapFrom(src =>
                src.Comments != null ? src.Comments.Count(c => c.IsApproved) : 0));

        // Nested DTOs
        CreateMap<User, PostAuthorDto>();
        CreateMap<Category, PostCategoryDto>();
        CreateMap<Tag, PostTagDto>();
    }
}

