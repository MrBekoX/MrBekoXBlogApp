using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAgentProposal : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "agent_proposals",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ProposalId = table.Column<Guid>(type: "uuid", nullable: false),
                    Version = table.Column<long>(type: "bigint", nullable: false),
                    RunId = table.Column<Guid>(type: "uuid", nullable: false),
                    ArticleId = table.Column<Guid>(type: "uuid", nullable: false),
                    ArticleRevision = table.Column<long>(type: "bigint", nullable: false),
                    BaseContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    ContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    Summary = table.Column<string>(type: "character varying(8000)", maxLength: 8000, nullable: false),
                    OwnerKey = table.Column<string>(type: "character varying(160)", maxLength: 160, nullable: false),
                    ExpiresAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    Status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    ConfirmedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    ConfirmedContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: true),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    UpdatedBy = table.Column<string>(type: "text", nullable: true),
                    IsDeleted = table.Column<bool>(type: "boolean", nullable: false),
                    DeletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_agent_proposals", x => x.Id);
                    table.CheckConstraint("CK_agent_proposals_status", "\"Status\" IN ('proposed', 'confirmed', 'resume_sent')");
                });

            migrationBuilder.CreateIndex(
                name: "IX_agent_proposals_owner_status",
                table: "agent_proposals",
                columns: new[] { "OwnerKey", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_agent_proposals_run",
                table: "agent_proposals",
                column: "RunId");

            migrationBuilder.CreateIndex(
                name: "UX_agent_proposals_proposal_content",
                table: "agent_proposals",
                columns: new[] { "ProposalId", "ContentHash" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "UX_agent_proposals_proposal_version",
                table: "agent_proposals",
                columns: new[] { "ProposalId", "Version" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "agent_proposals");
        }
    }
}
