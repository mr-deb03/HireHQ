"""Production configuration guards.

`APP_ENV=production` is baked into the container image, so it is set even when the host
supplies nothing at all. That makes the "no configuration arrived" case common on a first
deployment — and makes it important that the error names *that* rather than the first
individual check to fail, which sends people hunting for a secrets problem they do not
have.
"""

from __future__ import annotations

import pytest

from app.core.config import DEV_JWT_SECRET, Settings

STRONG = "x" * 48

#: A complete, valid production environment. Individual tests break one thing at a time.
VALID = {
    "APP_ENV": "production",
    "DEBUG": "false",
    "JWT_SECRET": STRONG,
    "DATABASE_URL": "postgresql+asyncpg://user:pw@db.example.com/hirehq",
    "REDIS_URL": "rediss://default:pw@redis.example.com:6379",
    "STORAGE_PROVIDER": "s3",
    "STORAGE_ENDPOINT": "https://acct.r2.cloudflarestorage.com",
    "STORAGE_ACCESS_KEY": "key",
    "STORAGE_SECRET_KEY": "secret",
    "CORS_ORIGINS": "https://app.vercel.app",
}


def build(monkeypatch, **overrides) -> Settings:
    """Construct Settings from a controlled environment, ignoring any local .env."""
    for key in (
        "APP_ENV", "DEBUG", "JWT_SECRET", "DATABASE_URL", "REDIS_URL",
        "STORAGE_PROVIDER", "STORAGE_ENDPOINT", "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY", "CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    # _env_file=None so a developer's own .env cannot influence the result.
    return Settings(_env_file=None)


class TestNoConfigurationArrived:
    def test_names_the_real_cause_not_the_first_failed_check(self, monkeypatch):
        """The deployment failure this project actually hits.

        Only APP_ENV is set, because the image sets it. Reporting "JWT_SECRET must be
        strong" here is technically true and practically useless.
        """
        with pytest.raises(ValueError) as exc:
            build(monkeypatch, APP_ENV="production")

        message = str(exc.value)
        assert "No configuration reached this container" in message
        # It must say this is a deployment problem, not a secret problem.
        assert "not a bad secret" in message
        # And it must point at where to fix it.
        assert "Environment" in message

    def test_lists_which_settings_are_still_defaults(self, monkeypatch):
        with pytest.raises(ValueError) as exc:
            build(monkeypatch, APP_ENV="production")

        message = str(exc.value)
        for name in ("JWT_SECRET", "DATABASE_URL", "STORAGE_PROVIDER", "REDIS_URL"):
            assert name in message

    def test_partial_configuration_is_not_mistaken_for_none(self, monkeypatch):
        """Real settings present but a weak secret is a *different* problem, and must be
        reported as one - otherwise the diagnostic would misfire on a genuine mistake."""
        with pytest.raises(ValueError) as exc:
            build(monkeypatch, **{**VALID, "JWT_SECRET": "short"})

        message = str(exc.value)
        assert "No configuration reached" not in message
        assert "at least 32" in message


class TestIndividualGuards:
    def test_reports_every_problem_at_once(self, monkeypatch):
        """Fixing production config one redeploy at a time is miserable; the error names
        all of it."""
        with pytest.raises(ValueError) as exc:
            build(
                monkeypatch,
                **{**VALID, "JWT_SECRET": "short", "DEBUG": "true", "STORAGE_PROVIDER": "local"},
            )

        message = str(exc.value)
        assert "at least 32" in message
        assert "DEBUG must be false" in message
        assert "development-only backend" in message

    def test_dev_placeholder_secret_is_refused_with_a_way_to_fix_it(self, monkeypatch):
        with pytest.raises(ValueError) as exc:
            build(monkeypatch, **{**VALID, "JWT_SECRET": DEV_JWT_SECRET})

        message = str(exc.value)
        assert "development placeholder" in message
        # The remedy is in the message, so nobody has to go looking for it.
        assert "token_urlsafe" in message

    def test_local_storage_is_refused(self, monkeypatch):
        with pytest.raises(ValueError, match="development-only backend"):
            build(monkeypatch, **{**VALID, "STORAGE_PROVIDER": "local"})

    def test_debug_is_refused(self, monkeypatch):
        with pytest.raises(ValueError, match="DEBUG must be false"):
            build(monkeypatch, **{**VALID, "DEBUG": "true"})


class TestValidConfiguration:
    def test_a_complete_production_environment_boots(self, monkeypatch):
        settings = build(monkeypatch, **VALID)

        assert settings.APP_ENV == "production"
        assert settings.STORAGE_PROVIDER == "s3"
        assert settings.cors_origin_list == ["https://app.vercel.app"]

    def test_development_defaults_are_untouched(self, monkeypatch):
        """The guards apply only to production - the zero-setup local path must still
        work with no environment at all."""
        settings = build(monkeypatch)

        assert settings.APP_ENV == "development"
        assert settings.DATABASE_URL.startswith("sqlite")
        assert settings.JWT_SECRET == DEV_JWT_SECRET
