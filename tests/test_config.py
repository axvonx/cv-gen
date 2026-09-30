import pytest

from cv_gen.config import DEFAULT_ENGINE_REV, ConfigError, load_config


def write(tmp_path, text):
    path = tmp_path / "cvgen-tests.toml"
    path.write_text(text)
    return path


def test_defaults_and_relative_paths(tmp_path):
    config = load_config(write(tmp_path, '[project]\nfile = "a/b.cv"\n'))
    assert config.project_file == (tmp_path / "a/b.cv").resolve()
    assert config.server == "https://circuitverse.org"
    assert config.engine_rev == DEFAULT_ENGINE_REV
    assert (config.seed, config.max_cases, config.intensity) == (0, 256, 100)
    assert config.suites == ()


@pytest.mark.parametrize(
    "text",
    [
        '[project]\ntoken = "abc"\n',
        '[project]\napi_key = "abc"\n',
        '[[suite]]\nscope = "X"\noracle = "y"\npassword = "p"\n',
        '[auth]\nsecret = "s"\n',
    ],
)
def test_credentials_are_rejected(tmp_path, text):
    with pytest.raises(ConfigError, match="credentials never belong"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize(
    "text, fragment",
    [
        ('[projekt]\nfile = "x"\n', "unknown section"),
        ('[project]\nfiel = "x"\n', "unknown key"),
        ('[[suite]]\nscope = "X"\n', r"suite\[0\]\.oracle is required"),
        ('[[suite]]\nscope = "X"\noracle = "a"\n[[suite]]\nscope = "X"\noracle = "b"\n',
         "listed twice"),
        ('[generate]\nintensity = 101\n', "0..100"),
        ('[generate]\nmax_cases = true\n', "must be an integer"),
    ],
)
def test_schema_errors(tmp_path, text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(write(tmp_path, text))


def test_suite_overrides(tmp_path):
    config = load_config(write(
        tmp_path, '[[suite]]\nscope = "ALU"\noracle = "alu"\nmax_cases = 1024\nseed = 7\n'
    ))
    (suite,) = config.suites
    assert (suite.scope, suite.oracle, suite.max_cases, suite.seed) == ("ALU", "alu", 1024, 7)
    assert suite.intensity is None
