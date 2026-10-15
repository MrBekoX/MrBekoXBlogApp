"""Ortam değişkeni yapılandırma testleri: ``.env`` yükleme + tür dönüşümleri.

Kapsam: ``env_file`` ayrıştırma/öncelik/hata sözleşmesi; ``from_env`` okuyucularının
(messaging DB/broker, LLM sağlayıcı, içerik deposu) davranış korunumu; canlı giriş
noktasının (``service_main``) import edilebilirliği.

Tüm testler os.environ'ı izole eder (autouse fixture): ``AGENT_ENV_FILE`` silinir,
``AGENT_TEST_*`` önekli sahte değişkenler temizlenir ve ``.env`` yüklemesinin
os.environ'a sızdırdığı ``AGENT_TEST_*`` anahtarları teardown'da silinir. ``.env``
dosyaları tmp_path'te SAHTE değerlerle yazılır — gerçek sır yoktur (genel kural).

``app`` paketine bağımlı testler modül-seviyesi import YAPMAZ: pyproject
``pythonpath = ["app"]`` yalnız ``app`` DİZİNİNİ sys.path'e ekler; ``app``
namespace paketinin kendisi ancak hizmet kökü sys.path'teyken çözülür
(``app_importable`` fixture'ı bunu CWD'den bağımsız sağlar). ``env_file``/``
agent_core`` üst seviye modüllerdir ve doğrudan import edilir.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path

import pytest

import env_file
from env_file import EnvConfigError, EnvFileError, env_bool, env_float, env_int, load_env_file
from agent_core.adapters.config import LlmProviderSettings
from agent_core.adapters.http_content_repository import ContentRepositorySettings
from agent_core.errors import AgentErrorCode, PortError

#: (app paketi) için hizmet kökü: tests/test_env_config.py → parents[1].
_SERVICE_ROOT = Path(__file__).resolve().parents[1]

#: Keşif yolu (app dizini ve üstleri) üzerinde gerçek .env var mı?
#: Geliştirici makinesinde .env varsa "dosya yok → no-op" keşif testi koşamaz.
_DISCOVERY_HAS_ENV = any(
    (directory / ".env").is_file() for directory in Path(env_file.__file__).resolve().parents
)


@pytest.fixture(autouse=True)
def _isolate_agent_env(monkeypatch):
    """Her testte AGENT ortamını izole eder; .env sızıntılarını teardown'da siler."""

    monkeypatch.delenv("AGENT_ENV_FILE", raising=False)
    for name in [n for n in os.environ if n.startswith("AGENT_TEST_")]:
        monkeypatch.delenv(name, raising=False)
    yield
    # load_env_file doğrudan os.environ'a yazar; monkeypatch göremediği bu
    # anahtarları yalnız test anahtarı önekiyle (AGENT_TEST_) temizleriz.
    for name in [n for n in os.environ if n.startswith("AGENT_TEST_")]:
        os.environ.pop(name, None)


@pytest.fixture()
def app_importable(monkeypatch):
    """``app`` namespace paketini hizmet kökü sys.path'te yapar (CWD'den bağımsız).

    pyproject ``pythonpath = ["app"]`` yalnız ``app`` DİZİNİNİ eklediği için
    ``import app`` yalnız ``python -m pytest`` (CWD=hizmet kökü) koşumunda
    çözülür; bu fixture kapı/CI koşumlarında da deterministik çözüm verir.
    """

    monkeypatch.syspath_prepend(str(_SERVICE_ROOT))


@pytest.fixture()
def messaging_db(app_importable):
    """``app.messaging.db`` modülü (fixture zinciriyle app çözülebilir iken)."""

    from app.messaging import db

    return db


@pytest.fixture()
def messaging_settings(app_importable):
    """``app.messaging.settings`` modülü (fixture zinciriyle app çözülebilir iken)."""

    from app.messaging import settings

    return settings


# --------------------------------------------------------------- (a) ayrıştırma


def test_load_env_file_parses_pairs_comments_quotes_and_export(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# tam satır yorum\n"
        "\n"
        "AGENT_TEST_PLAIN=test-db-password\n"
        "export AGENT_TEST_EXPORTED=export-degeri\n"
        "AGENT_TEST_SINGLE='tek tırnak değer'\n"
        'AGENT_TEST_DOUBLE="çift tırnak değer"\n'
        "sadece_anahtar_satiri\n",
        encoding="utf-8",
    )

    loaded = load_env_file(str(env_path))

    assert loaded == {
        "AGENT_TEST_PLAIN": "test-db-password",
        "AGENT_TEST_EXPORTED": "export-degeri",
        "AGENT_TEST_SINGLE": "tek tırnak değer",
        "AGENT_TEST_DOUBLE": "çift tırnak değer",
    }
    assert os.environ["AGENT_TEST_PLAIN"] == "test-db-password"


def test_load_env_file_reports_line_number_without_leaking_content(
    tmp_path, caplog
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AGENT_TEST_OK=deger\n"
        "sadece_anahtar_satiri\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="env_file"):
        loaded = load_env_file(str(env_path))

    assert loaded == {"AGENT_TEST_OK": "deger"}
    assert any("2. satır" in record.getMessage() for record in caplog.records)
    # Anahtar/değer uyarıya sızmaz (değer hassas olabilir).
    assert "sadece_anahtar_satiri" not in caplog.text
    assert "=" not in caplog.text


def test_load_env_file_tolerates_bom(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"\xef\xbb\xbf" + "AGENT_TEST_BOM=bom-degeri\n".encode("utf-8"))

    loaded = load_env_file(str(env_path))

    assert loaded == {"AGENT_TEST_BOM": "bom-degeri"}


def test_load_env_file_last_duplicate_key_wins(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AGENT_TEST_DUP=ilk\n"
        "AGENT_TEST_DUP=son\n",
        encoding="utf-8",
    )

    loaded = load_env_file(str(env_path))

    assert loaded == {"AGENT_TEST_DUP": "son"}
    assert os.environ["AGENT_TEST_DUP"] == "son"


# ------------------------------------------------------------------ (b) öncelik


def test_load_env_file_does_not_override_existing_environ(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AGENT_TEST_PRIORITY=env-dosyasindan\n"
        "AGENT_TEST_YENI=yalniz-env-dosyasinda\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_TEST_PRIORITY", "gercek-ortam")

    loaded = load_env_file(str(env_path))

    # Gerçek ortam .env'i ezer (setdefault semantiği).
    assert os.environ["AGENT_TEST_PRIORITY"] == "gercek-ortam"
    assert "AGENT_TEST_PRIORITY" not in loaded
    # Yalnız yeni uygulanan anahtarlar döner.
    assert loaded == {"AGENT_TEST_YENI": "yalniz-env-dosyasinda"}


# ------------------------------------------------------- (c) dosya yok → no-op


@pytest.mark.skipif(_DISCOVERY_HAS_ENV, reason="keşif yolunda gerçek .env var; keşif no-op testi uygulanamaz")
def test_load_env_file_without_any_file_is_silent_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_ENV_FILE", raising=False)
    # CWD'de .env olsa bile keşif CWD'ye bakmaz (bkz. (e)); ortamda dosya yokken
    # yükleme no-op olmalıdır.
    (tmp_path / ".env").write_text("AGENT_TEST_CWD_DECOY=deger\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    loaded = load_env_file()

    assert loaded == {}
    assert "AGENT_TEST_CWD_DECOY" not in os.environ


# ------------------------------------------------------- (d) AGENT_ENV_FILE yolu


def test_load_env_file_with_env_var_path_loads_file(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / "ozel.env"
    env_path.write_text("AGENT_TEST_EXPLICIT=yol-dosyasi\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_ENV_FILE", str(env_path))

    loaded = load_env_file()

    assert loaded == {"AGENT_TEST_EXPLICIT": "yol-dosyasi"}
    assert os.environ["AGENT_TEST_EXPLICIT"] == "yol-dosyasi"


def test_load_env_file_missing_env_var_path_raises_env_file_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ENV_FILE", str(tmp_path / "yok.env"))

    with pytest.raises(EnvFileError, match="AGENT_ENV_FILE"):
        load_env_file()


def test_load_env_file_explicit_path_parameter_loads_file(tmp_path) -> None:
    env_path = tmp_path / "param.env"
    env_path.write_text("AGENT_TEST_PARAM=parametre-yolu\n", encoding="utf-8")

    loaded = load_env_file(str(env_path))

    assert loaded == {"AGENT_TEST_PARAM": "parametre-yolu"}


# ------------------------------------------------------------- (e) CWD bağımsızlığı


def test_load_env_file_is_independent_of_cwd(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("AGENT_TEST_CWD=ayni-sonuc\n", encoding="utf-8")

    before = load_env_file(str(env_path))
    # İlk yükleme anahtarı os.environ'a yazdı; setdefault semantiği (idempotentlik)
    # ikinci çağrıyı boş döndürür. CWD etkisini yalıtmak için temizliyoruz.
    os.environ.pop("AGENT_TEST_CWD", None)
    monkeypatch.chdir(tmp_path)  # keşif modül konumundan yürür; CWD fark etmez
    after = load_env_file(str(env_path))

    assert before == after == {"AGENT_TEST_CWD": "ayni-sonuc"}


@pytest.mark.skipif(_DISCOVERY_HAS_ENV, reason="keşif yolunda gerçek .env var; keşif testleri os.environ'ı kirletir")
def test_load_env_file_discovery_ignores_cwd_env_file(tmp_path, monkeypatch) -> None:
    """Keşif app dizininden hizmet köküne bakar; CWD'ye bırakılan .env yüklenmez."""

    (tmp_path / ".env").write_text("AGENT_TEST_CWD_DECOY=deger\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    loaded = load_env_file()

    assert "AGENT_TEST_CWD_DECOY" not in loaded
    assert "AGENT_TEST_CWD_DECOY" not in os.environ


def test_env_file_discovery_is_bounded_to_service_root() -> None:
    """Keşif zinciri hizmet kökünde (pyproject.toml) durur; üst dizinler yoklanmaz."""

    chain = env_file._search_dirs()

    assert chain, "arama zinciri boş olmamalı"
    assert chain[-1] == _SERVICE_ROOT
    assert (chain[-1] / "pyproject.toml").is_file()


# ------------------------------------------------------- (f) tür dönüşüm yardımcıları


def test_env_int_converts_and_falls_back() -> None:
    assert env_int("AGENT_TEST_INT", 5, {"AGENT_TEST_INT": "7"}) == 7
    assert env_int("AGENT_TEST_INT", 5, {}) == 5
    assert env_int("AGENT_TEST_INT", 5, {"AGENT_TEST_INT": ""}) == 5
    assert env_int("AGENT_TEST_INT", 5, {"AGENT_TEST_INT": "   "}) == 5


def test_env_int_invalid_value_raises_without_leaking_raw_value() -> None:
    with pytest.raises(EnvConfigError) as excinfo:
        env_int("AGENT_TEST_INT", 5, {"AGENT_TEST_INT": "yedi"})

    assert "AGENT_TEST_INT" in str(excinfo.value)
    assert "yedi" not in str(excinfo.value)


def test_env_float_converts_via_os_environ(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TEST_FLOAT", "2.5")

    assert env_float("AGENT_TEST_FLOAT", 1.0) == 2.5  # environ=None → os.environ
    assert env_float("AGENT_TEST_FLOAT", 1.0, {}) == 1.0


def test_env_float_invalid_value_names_variable_only() -> None:
    with pytest.raises(EnvConfigError) as excinfo:
        env_float("AGENT_TEST_FLOAT", 1.0, {"AGENT_TEST_FLOAT": "hizli"})

    assert "AGENT_TEST_FLOAT" in str(excinfo.value)
    assert "hizli" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("On", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("OFF", False),
    ],
)
def test_env_bool_accepts_known_values(raw: str, expected: bool) -> None:
    assert env_bool("AGENT_TEST_BOOL", True, {"AGENT_TEST_BOOL": raw}) is expected


def test_env_bool_falls_back_to_default_on_empty() -> None:
    assert env_bool("AGENT_TEST_BOOL", False, {}) is False
    assert env_bool("AGENT_TEST_BOOL", False, {"AGENT_TEST_BOOL": "  "}) is False


def test_env_bool_invalid_value_names_variable_only() -> None:
    with pytest.raises(EnvConfigError) as excinfo:
        env_bool("AGENT_TEST_BOOL", False, {"AGENT_TEST_BOOL": "belki"})

    assert "AGENT_TEST_BOOL" in str(excinfo.value)
    assert "belki" not in str(excinfo.value)


# ------------------------------------------------------- (g) LlmProviderSettings


def test_llm_settings_from_env_without_key_returns_none() -> None:
    assert LlmProviderSettings.from_env({}) is None
    assert LlmProviderSettings.from_env({"AGENT_LLM_API_KEY": ""}) is None


def test_llm_settings_with_key_but_no_model_raises_config_error() -> None:
    with pytest.raises(PortError) as excinfo:
        LlmProviderSettings.from_env({"AGENT_LLM_API_KEY": "sk-test-fake-anahtar-degil"})

    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "AGENT_LLM_MODEL" in excinfo.value.message


def test_llm_settings_invalid_request_timeout_raises_env_config_error() -> None:
    environ = {
        "AGENT_LLM_API_KEY": "sk-test-fake-anahtar-degil",
        "AGENT_LLM_MODEL": "test-model",
        "AGENT_LLM_REQUEST_TIMEOUT": "hizli",
    }

    with pytest.raises(EnvConfigError) as excinfo:
        LlmProviderSettings.from_env(environ)

    assert "AGENT_LLM_REQUEST_TIMEOUT" in str(excinfo.value)
    assert "hizli" not in str(excinfo.value)


def test_llm_settings_valid_environ_maps_fields() -> None:
    settings = LlmProviderSettings.from_env(
        {
            "AGENT_LLM_API_KEY": "sk-test-fake-anahtar-degil",
            "AGENT_LLM_MODEL": "test-model",
            "AGENT_LLM_BASE_URL": "http://llm.test/v1",
            "AGENT_LLM_CONNECT_TIMEOUT": "3.5",
            "AGENT_LLM_REQUEST_TIMEOUT": "60",
        }
    )

    assert settings is not None
    assert settings.model == "test-model"
    assert settings.base_url == "http://llm.test/v1"
    assert settings.connect_timeout_seconds == 3.5
    assert settings.request_timeout_seconds == 60.0


# ----------------------------------------------------------- (h) messaging.db


def test_db_from_env_without_password_raises_agent_db_error(messaging_db) -> None:
    with pytest.raises(messaging_db.AgentDbError) as excinfo:
        messaging_db.from_env({})

    assert "AGENT_DB_PASSWORD" in str(excinfo.value)


def test_db_from_env_invalid_port_raises_env_config_error(messaging_db) -> None:
    environ = {"AGENT_DB_PASSWORD": "test-db-password", "AGENT_DB_PORT": "besbinuc"}

    with pytest.raises(EnvConfigError) as excinfo:
        messaging_db.from_env(environ)

    assert "AGENT_DB_PORT" in str(excinfo.value)
    assert "besbinuc" not in str(excinfo.value)


def test_db_from_env_with_fake_password_keeps_defaults(messaging_db) -> None:
    settings = messaging_db.from_env({"AGENT_DB_PASSWORD": "test-db-password"})

    assert settings.port == 5432
    assert settings.host == "127.0.0.1"
    assert settings.min_size == 1
    assert settings.max_size == 4


# ------------------------------------------------------- (i) messaging.settings


def test_broker_from_env_empty_environ_keeps_defaults(messaging_settings) -> None:
    assert messaging_settings.from_env({}) == messaging_settings.BrokerSettings()


def test_broker_from_env_maps_values(messaging_settings) -> None:
    settings = messaging_settings.from_env(
        {
            "AGENT_BROKER_HOST": "broker.test",
            "AGENT_BROKER_PORT": "5673",
            "AGENT_BROKER_PASSWORD": "test-broker-password",
            "AGENT_BROKER_HEARTBEAT": "15",
            "AGENT_BROKER_PREFETCH": "8",
        }
    )

    assert settings.host == "broker.test"
    assert settings.port == 5673
    assert settings.password == "test-broker-password"
    assert settings.heartbeat_seconds == 15
    assert settings.prefetch_count == 8


def test_broker_from_env_invalid_prefetch_raises_env_config_error(messaging_settings) -> None:
    with pytest.raises(EnvConfigError) as excinfo:
        messaging_settings.from_env({"AGENT_BROKER_PREFETCH": "onalti"})

    assert "AGENT_BROKER_PREFETCH" in str(excinfo.value)
    assert "onalti" not in str(excinfo.value)


# ------------------------------------------- (j) içerik deposu (HttpContentRepository)


def test_content_settings_without_base_url_returns_none() -> None:
    assert ContentRepositorySettings.from_env({}) is None
    assert ContentRepositorySettings.from_env({"AGENT_CONTENT_BASE_URL": ""}) is None


def test_content_settings_base_url_without_service_key_raises_config_error() -> None:
    with pytest.raises(PortError) as excinfo:
        ContentRepositorySettings.from_env({"AGENT_CONTENT_BASE_URL": "http://content.test/api/v1"})

    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "AGENT_CONTENT_SERVICE_KEY" in excinfo.value.message


def test_content_settings_valid_environ_maps_fields_and_default_timeout() -> None:
    settings = ContentRepositorySettings.from_env(
        {
            "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
            "AGENT_CONTENT_SERVICE_KEY": "test-service-key",
        }
    )

    assert settings is not None
    assert settings.base_url == "http://content.test/api/v1"
    assert settings.service_key == "test-service-key"
    assert settings.timeout_seconds == 10.0


def test_content_settings_invalid_timeout_raises_env_config_error() -> None:
    environ = {
        "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
        "AGENT_CONTENT_SERVICE_KEY": "test-service-key",
        "AGENT_CONTENT_TIMEOUT_SECONDS": "yavas",
    }

    with pytest.raises(EnvConfigError) as excinfo:
        ContentRepositorySettings.from_env(environ)

    assert "AGENT_CONTENT_TIMEOUT_SECONDS" in str(excinfo.value)
    assert "yavas" not in str(excinfo.value)


# ------------------------------------------- (k) canlı giriş noktası import dumanı


def test_service_main_module_importable(app_importable) -> None:
    from app import service_main

    assert hasattr(service_main, "build_components_async")
    assert hasattr(service_main, "run_service")
    # .env yüklemesi giriş noktasında, logging yapılandırmasından önce yapılır
    # (AGENT_LOG_LEVEL da .env'den gelebilsin diye) — statik duman kanıtı.
    assert "load_env_file" in inspect.getsource(service_main._async_main)
