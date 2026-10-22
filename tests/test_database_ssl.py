from configure.project_config import ProjectConfig


def test_mysql_ssl_config_enables_encrypted_connection_without_ca():
    config = ProjectConfig(
        _env_file=None,
        DATABASE_URL="",
        DATABASE_USERNAME="template_user",
        DATABASE_PASSWORD="p@ss",
        DATABASE_HOST="db.example",
        DATABASE_PORT="3306",
        DATABASE_SSL_ENABLED=True,
    )

    assert config.DATABASE_CONNECTIONS["default"]["credentials"]["ssl"] == {
        "verify_mode": False,
    }
    assert "ssl=true" in config.DATABASE_URL


def test_mysql_ssl_config_uses_ca_for_server_verification():
    config = ProjectConfig(
        _env_file=None,
        DATABASE_URL="",
        DATABASE_USERNAME="template_user",
        DATABASE_PASSWORD="p@ss",
        DATABASE_HOST="db.example",
        DATABASE_PORT="3306",
        DATABASE_SSL_ENABLED=True,
        DATABASE_SSL_CA="D:/certs/ca.pem",
    )

    assert config.DATABASE_CONNECTIONS["default"]["credentials"]["ssl"] == {
        "verify_mode": True,
        "ca": "D:/certs/ca.pem",
        "check_hostname": True,
    }
