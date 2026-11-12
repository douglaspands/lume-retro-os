"""README credits the FB Alpha 2012 cores and states their non-commercial license
(catalog-arcade-sega, task 2.3)."""

from r36os import catalog
from r36os.paths import REPO_ROOT

README = (REPO_ROOT / "README.md").read_text()


def _section(title: str) -> str:
    return README.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def test_acknowledgements_credit_fbalpha2012():
    text = _section("Agradecimentos")
    assert "FB Alpha 2012" in text
    for core in ("fbalpha2012_cps1", "fbalpha2012_cps2", "fbalpha2012_neogeo"):
        assert core in text


def test_license_states_the_non_commercial_restriction():
    text = _section("Licença")
    assert "FB Alpha 2012" in text
    assert "não\n  comercial" in text or "não comercial" in text
    assert "venda" in text and "doações" in text
    assert "/usr/share/licenses/" in text


def test_every_fbalpha2012_core_of_the_catalog_is_in_the_readme():
    cores = [c for c in catalog.load()["cores"] if c.startswith("fbalpha2012_")]
    assert cores
    for core in cores:
        assert core in _section("Agradecimentos")
