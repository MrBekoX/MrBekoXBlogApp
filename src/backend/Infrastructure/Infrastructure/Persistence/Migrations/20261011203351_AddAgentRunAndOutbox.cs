using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAgentRunAndOutbox : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "agent_runs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ConversationId = table.Column<Guid>(type: "uuid", nullable: false),
                    TurnSequence = table.Column<long>(type: "bigint", nullable: false),
                    OwnerKey = table.Column<string>(type: "character varying(160)", maxLength: 160, nullable: false),
                    OwnerUserId = table.Column<Guid>(type: "uuid", nullable: true),
                    GuestSessionId = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    IdempotencyKey = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    IdempotencyPayloadHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    Status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    Question = table.Column<string>(type: "character varying(8000)", maxLength: 8000, nullable: false),
                    Language = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    ModePreference = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    BudgetProfile = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    ArticleId = table.Column<Guid>(type: "uuid", nullable: true),
                    ArticleContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    ContextSnapshotReference = table.Column<string>(type: "character varying(512)", maxLength: 512, nullable: false),
                    ContextSnapshotJson = table.Column<string>(type: "jsonb", nullable: false),
                    DeadlineAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    AcceptedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: true),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    UpdatedBy = table.Column<string>(type: "text", nullable: true),
                    IsDeleted = table.Column<bool>(type: "boolean", nullable: false),
                    DeletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_agent_runs", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "outbox_messages",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    MessageId = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    MessageType = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    Exchange = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    RoutingKey = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    CorrelationId = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    RunId = table.Column<Guid>(type: "uuid", nullable: true),
                    EnvelopeJson = table.Column<string>(type: "text", nullable: false),
                    Status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    ClaimedBy = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: true),
                    ClaimedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ClaimLeaseUntil = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    AttemptCount = table.Column<int>(type: "integer", nullable: false),
                    LastError = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true),
                    LastAttemptAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    PublishedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: true),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    UpdatedBy = table.Column<string>(type: "text", nullable: true),
                    IsDeleted = table.Column<bool>(type: "boolean", nullable: false),
                    DeletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_outbox_messages", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_agent_runs_article",
                table: "agent_runs",
                column: "ArticleId");

            migrationBuilder.CreateIndex(
                name: "IX_agent_runs_owner_status",
                table: "agent_runs",
                columns: new[] { "OwnerKey", "Status" });

            migrationBuilder.CreateIndex(
                name: "UX_agent_runs_conversation_turn",
                table: "agent_runs",
                columns: new[] { "ConversationId", "TurnSequence" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "UX_agent_runs_owner_idempotency",
                table: "agent_runs",
                columns: new[] { "OwnerKey", "IdempotencyKey" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_outbox_messages_run",
                table: "outbox_messages",
                column: "RunId");

            migrationBuilder.CreateIndex(
                name: "IX_outbox_messages_status_lease",
                table: "outbox_messages",
                columns: new[] { "Status", "ClaimLeaseUntil" });

            migrationBuilder.CreateIndex(
                name: "UX_outbox_messages_message_id",
                table: "outbox_messages",
                column: "MessageId",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "agent_runs");

            migrationBuilder.DropTable(
                name: "outbox_messages");
        }
    }
}
