import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
AUTH = ROOT / "scripts/sourcehut_auth.sh"


class SourceHutAuthTests(unittest.TestCase):
    def run_auth(self, env: dict[str, str]) -> str:
        result = subprocess.run(
            [
                "bash",
                "-xc",
                f'source "{AUTH}"; sourcehut_auth; python3 -c \'import os; assert os.environ.get("SRHT_TOKEN")\'; case $- in *x*) printf "XTRACE_ON\\n";; *) printf "XTRACE_OFF\\n";; esac',
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )
        return result.stdout

    def test_existing_token_is_not_traced(self) -> None:
        sentinel = "existing-token-sentinel"
        output = self.run_auth({**os.environ, "SRHT_TOKEN": sentinel})
        self.assertNotIn(sentinel, output)
        self.assertIn("XTRACE_ON", output)

    def test_oauth_token_is_not_traced(self) -> None:
        sentinel = "oauth-token-sentinel"
        env = {**os.environ, "OAUTH2_TOKEN": sentinel}
        env.pop("SRHT_TOKEN", None)
        output = self.run_auth(env)
        self.assertNotIn(sentinel, output)
        self.assertIn("XTRACE_ON", output)

    def test_config_token_is_not_traced(self) -> None:
        sentinel = "config-token-sentinel"
        with tempfile.TemporaryDirectory() as tmp:
            config = pathlib.Path(tmp) / ".config/hut"
            config.mkdir(parents=True)
            (config / "config").write_text(f'access-token "{sentinel}"\n')
            env = {**os.environ, "HOME": tmp}
            env.pop("SRHT_TOKEN", None)
            env.pop("OAUTH2_TOKEN", None)
            output = self.run_auth(env)
        self.assertNotIn(sentinel, output)
        self.assertIn("XTRACE_ON", output)

    def test_disabled_xtrace_stays_disabled(self) -> None:
        sentinel = "no-trace-token-sentinel"
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{AUTH}"; sourcehut_auth; case $- in *x*) printf "XTRACE_ON\\n";; *) printf "XTRACE_OFF\\n";; esac',
            ],
            env={**os.environ, "SRHT_TOKEN": sentinel},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )
        self.assertNotIn(sentinel, result.stdout)
        self.assertIn("XTRACE_OFF", result.stdout)


if __name__ == "__main__":
    unittest.main()
