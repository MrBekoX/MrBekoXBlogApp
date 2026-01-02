using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Server.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddSearchVector : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_posts_CategoryId",
                table: "posts");

            migrationBuilder.CreateIndex(
                name: "IX_posts_categoryid_status",
                table: "posts",
                columns: new[] { "CategoryId", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_posts_isdeleted_status",
                table: "posts",
                columns: new[] { "IsDeleted", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_posts_status_isfeatured_publishedat",
                table: "posts",
                columns: new[] { "Status", "IsFeatured", "PublishedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_posts_status_publishedat",
                table: "posts",
                columns: new[] { "Status", "PublishedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_posts_title",
                table: "posts",
                column: "Title");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_posts_categoryid_status",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_posts_isdeleted_status",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_posts_status_isfeatured_publishedat",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_posts_status_publishedat",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_posts_title",
                table: "posts");

            migrationBuilder.CreateIndex(
                name: "IX_posts_CategoryId",
                table: "posts",
                column: "CategoryId");
        }
    }
}
