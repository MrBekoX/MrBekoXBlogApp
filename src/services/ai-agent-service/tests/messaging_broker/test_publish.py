"""Yayın kabul ölçütleri: publisher confirm, persistent mesaj, AMQP zarf tutarlılığı,
bağlanmamış routing key'in fark edilmesi ve payload üst sınırı."""

from __future__ import annotations

import pytest

from messaging import BACKEND_EVENTS_QUEUE, BrokerPublisher, connect_broker
from messaging.connection import broker_connection
from messaging.contracts import AgentEnvelope, MAX_PAYLOAD_BYTES

from .conftest import AGENT_USER, ADMIN, make_settings, read_fixture, run


def _agent_envelope(fixture_path: str) -> AgentEnvelope:
    return AgentEnvelope(**read_fixture(fixture_path))


def test_publish_envelope_confirms_and_persists_with_amqp_properties() -> None:
    """Confirm alınır; mesaj persistent; AMQP properties zarfla tutarlı (plan satır 233)."""

    async def scenario() -> None:
        envelope = _agent_envelope("valid/agent.run.completed.json")
        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            publisher = BrokerPublisher(conn, exchanges=("blog.agent.events",))
            await publisher.start()
            result = await publisher.publish_envelope(envelope)
            assert result.confirmed is True
            assert result.returned is False
            await publisher.close()

        # broker'a düşen mesajı admin bağlantısıyla doğrula
        async with broker_connection(make_settings(*ADMIN)) as admin_conn:
            channel = await admin_conn.channel(publisher_confirms=False)
            queue = await channel.declare_queue(BACKEND_EVENTS_QUEUE, passive=True)
            message = await queue.get(fail=False, timeout=5.0)
            assert message is not None, "olay kuyruğa düşmedi"
            assert message.message_id == envelope.message_id
            assert message.correlation_id == envelope.correlation_id
            assert message.type == envelope.message_type
            assert message.content_type == "application/json"
            assert int(message.delivery_mode) == 2, "kalıcı mesaj beklendi (persistent)"
            body = message.body  # bytes: teslim sonrası kullanım için güvenli kopya
            parsed = AgentEnvelope.model_validate_json(body)
            assert parsed.message_id == envelope.message_id
            await message.ack()
            await channel.close()

    run(scenario())


def test_mandatory_unroutable_routing_key_is_reported() -> None:
    """Bağlanmamış routing key basic.return ile fark edilir; başarı sayılmaz."""

    async def scenario() -> None:
        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            publisher = BrokerPublisher(conn, exchanges=("blog.agent.events",))
            await publisher.start()
            result = await publisher.publish_raw(
                "blog.agent.events",
                "zz.b2.unroutable.v1",  # bindings: agent.run.# + agent.action.# -> eşleşmez
                b'{"probe":"unroutable"}',
                message_id="0b7b6f3e-0000-4000-8000-000000000001",
                correlation_id="0b7b6f3e-0000-4000-8000-000000000002",
                type_name="agent.run.completed",
            )
            assert result.returned is True
            assert result.confirmed is False
            assert "unroutable" in result.detail
            await publisher.close()

    run(scenario())


def test_publisher_rejects_agent_direction_violation() -> None:
    """Agent yalnız agent_to_backend türleri yayınlayabilir (B1 producer kuralı)."""

    async def scenario() -> None:
        envelope = _agent_envelope("valid/agent.cancel.requested.json")  # backend türü
        envelope = envelope.model_copy(update={"producer": "agent-py"})
        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            publisher = BrokerPublisher(conn, exchanges=("blog.agent.events",))
            await publisher.start()
            with pytest.raises(ValueError, match="yön"):
                await publisher.publish_envelope(envelope)
            await publisher.close()

    run(scenario())


def test_publisher_rejects_oversized_payload() -> None:
    """Sözleşme payload üst sınırı (256 KiB) yayından önce reddedilir."""

    async def scenario() -> None:
        envelope = _agent_envelope("valid/agent.run.completed.json")
        envelope = envelope.model_copy(
            update={"payload": {**envelope.payload, "answer": "x" * (MAX_PAYLOAD_BYTES + 1)}}
        )
        async with broker_connection(make_settings(*AGENT_USER)) as conn:
            publisher = BrokerPublisher(conn, exchanges=("blog.agent.events",))
            await publisher.start()
            with pytest.raises(ValueError, match="üst sınır"):
                await publisher.publish_envelope(envelope)
            await publisher.close()

    run(scenario())
