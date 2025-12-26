FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Copy csproj files and restore dependencies
COPY ["BlogApp.Server.Api/BlogApp.Server.Api.csproj", "BlogApp.Server.Api/"]
COPY ["BlogApp.Server.Application/BlogApp.Server.Application.csproj", "BlogApp.Server.Application/"]
COPY ["BlogApp.Server.Infrastructure/BlogApp.Server.Infrastructure.csproj", "BlogApp.Server.Infrastructure/"]
COPY ["BlogApp.Server.Domain/BlogApp.Server.Domain.csproj", "BlogApp.Server.Domain/"]

RUN dotnet restore "BlogApp.Server.Api/BlogApp.Server.Api.csproj"

# Copy everything else and build
COPY . .
WORKDIR "/src/BlogApp.Server.Api"
RUN dotnet build "BlogApp.Server.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BlogApp.Server.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app

# Create non-root user for security
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --disabled-password --gecos "" appuser

COPY --from=publish /app/publish .

# Create uploads directory with correct ownership
RUN mkdir -p /app/uploads && \
    chown -R appuser:appgroup /app/uploads && \
    chmod 755 /app/uploads

# Switch to non-root user
USER appuser

ENTRYPOINT ["dotnet", "BlogApp.Server.Api.dll"]

