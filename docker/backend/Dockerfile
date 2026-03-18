# Build stage
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Copy solution and project files (layer cached until .csproj changes)
COPY ["BlogApp.sln", "./"]
COPY ["src/BlogApp.Server/BlogApp.Server.Domain/BlogApp.Server.Domain.csproj", "src/BlogApp.Server/BlogApp.Server.Domain/"]
COPY ["src/BlogApp.Server/BlogApp.Server.Application/BlogApp.Server.Application.csproj", "src/BlogApp.Server/BlogApp.Server.Application/"]
COPY ["src/BlogApp.Server/BlogApp.Server.Infrastructure/BlogApp.Server.Infrastructure.csproj", "src/BlogApp.Server/BlogApp.Server.Infrastructure/"]
COPY ["src/BlogApp.Server/BlogApp.Server.Api/BlogApp.Server.Api.csproj", "src/BlogApp.Server/BlogApp.Server.Api/"]
COPY ["src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/BlogApp.BuildingBlocks.Caching.csproj", "src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/"]
COPY ["src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/BlogApp.BuildingBlocks.Messaging.csproj", "src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/"]

# Restore dependencies (cached until .csproj/.sln changes)
RUN dotnet restore "src/BlogApp.Server/BlogApp.Server.Api/BlogApp.Server.Api.csproj"

# Copy only backend + BuildingBlocks source (not frontend/ai-agent)
COPY ["src/BlogApp.Server/", "src/BlogApp.Server/"]
COPY ["src/BlogApp.BuildingBlocks/", "src/BlogApp.BuildingBlocks/"]

# Publish directly (includes build - no need for separate dotnet build)
WORKDIR "/src/src/BlogApp.Server/BlogApp.Server.Api"
RUN dotnet publish "BlogApp.Server.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Runtime stage
FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app

# Install health check dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Copy published app
COPY --from=build /app/publish .

# Create uploads directory for file storage
RUN mkdir -p /app/uploads && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Set ASP.NET Core environment
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production

ENTRYPOINT ["dotnet", "BlogApp.Server.Api.dll"]
