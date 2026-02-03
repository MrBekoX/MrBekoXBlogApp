using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Server.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAiFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<int>(
                name: "AiEstimatedReadingTime",
                table: "posts",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AiKeywords",
                table: "posts",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "AiProcessedAt",
                table: "posts",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AiSeoDescription",
                table: "posts",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AiSummary",
                table: "posts",
                type: "text",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "AiEstimatedReadingTime",
                table: "posts");

            migrationBuilder.DropColumn(
                name: "AiKeywords",
                table: "posts");

            migrationBuilder.DropColumn(
                name: "AiProcessedAt",
                table: "posts");

            migrationBuilder.DropColumn(
                name: "AiSeoDescription",
                table: "posts");

            migrationBuilder.DropColumn(
                name: "AiSummary",
                table: "posts");
        }
    }
}
