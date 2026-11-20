"""README credits the FB Alpha 2012 cores and states their non-commercial license
(catalog-arcade-sega, task 2.3)."""

from lume_tool import catalog
from lume_tool.paths import REPO_ROOT

README = (REPO_ROOT / "README.md").read_text()


def _section(title: str) -> str:
    return README.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def test_acknowledgements_credit_fbalpha2012():
    text = _section("Agradecimentos")
    assert "FB Alpha 2012" in text and "MAME 2003-Plus" in text
    # game-experience-tuning 10.5: the full core replaced the per-board cuts
    for core in ("`fbalpha2012`", "`mame2003_plus`"):
        assert core in text


def test_license_states_the_non_commercial_restriction():
    text = _section("Licença")
    assert "FB Alpha 2012" in text
    assert "não\n  comercial" in text or "não comercial" in text
    assert "venda" in text and "doações" in text
    assert "/usr/share/licenses/" in text


def test_every_fbalpha2012_core_of_the_catalog_is_in_the_readme():
    cores = [c for c in catalog.load()["cores"] if c.startswith(("fbalpha2012", "mame"))]
    assert cores
    for core in cores:
        assert f"`{core}`" in _section("Agradecimentos")
