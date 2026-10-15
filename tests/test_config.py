from gridpulse.config import pg_env


def test_pg_env_from_neon_style_url():
    env = pg_env(
        "postgresql://gp_owner:p%40ss@ep-x-123.eu-central-1.aws.neon.tech/gridpulse?sslmode=require"
    )
    assert env == {
        "PGHOST": "ep-x-123.eu-central-1.aws.neon.tech",
        "PGPORT": "5432",
        "PGUSER": "gp_owner",
        "PGPASSWORD": "p@ss",
        "PGDATABASE": "gridpulse",
        "PGSSLMODE": "require",
    }


def test_pg_env_without_password_relies_on_pgpass():
    env = pg_env("postgresql://postgres@localhost:5432/gridpulse")
    assert "PGPASSWORD" not in env
    assert env["PGDATABASE"] == "gridpulse"
