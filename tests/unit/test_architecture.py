"""Import-boundary rules (ADR-016.1), enforced by parsing imports with `ast`."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "acme_agent"
FORBIDDEN_EXTERNAL = {"google", "fastapi", "starlette", "httpx", "aiofiles", "structlog"}
PROJECT_PACKAGES = {"domain", "interview", "agent", "knowledge", "analysis", "storage", "web"}


def imported_modules(path: Path, root: Path) -> set[str]:
    """Absolute dotted names imported by a file; `root` is the `acme_agent` package dir."""
    rel = path.relative_to(root).with_suffix("")
    package = ["acme_agent", *rel.parts[:-1]]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                if node.module:
                    names.add(".".join([*base, node.module]))
                else:
                    names.update(".".join([*base, a.name]) for a in node.names)
            elif node.module:
                names.add(node.module)
    return names


def violations(package_dir: Path, allowed_project: set[str]) -> list[str]:
    """Rule breaches in `package_dir`; `allowed_project` are sibling packages it may import."""
    found: list[str] = []
    own = package_dir.name
    for path in sorted(package_dir.rglob("*.py")):
        for mod in imported_modules(path, package_dir.parent):
            parts = mod.split(".")
            if parts[0] in FORBIDDEN_EXTERNAL:
                found.append(f"{path.name}: forbidden import {mod}")
            elif parts[0] == "acme_agent":
                target = parts[1] if len(parts) > 1 else ""
                unknown = target not in PROJECT_PACKAGES and target not in ("", own)
                if unknown or target in PROJECT_PACKAGES - {own} - allowed_project:
                    found.append(f"{path.name}: forbidden import {mod}")
    return found


def test_domain_imports_nothing_from_project() -> None:
    assert violations(SRC / "domain", set()) == []


def test_interview_imports_only_domain() -> None:
    assert violations(SRC / "interview", {"domain"}) == []


def test_negative_case_detects_forbidden_import(tmp_path: Path) -> None:
    pkg = tmp_path / "domain"
    pkg.mkdir()
    (pkg / "bad.py").write_text("import fastapi\nfrom acme_agent.storage import x\n")
    found = violations(pkg, set())
    assert any("fastapi" in v for v in found)
    assert any("acme_agent.storage" in v for v in found)


def test_negative_case_allows_permitted_import(tmp_path: Path) -> None:
    pkg = tmp_path / "interview"
    pkg.mkdir()
    (pkg / "ok.py").write_text("from acme_agent.domain import models\nimport json\n")
    assert violations(pkg, {"domain"}) == []


def test_no_environment_reads_outside_config() -> None:
    for path in SRC.rglob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text()
        assert "os.environ" not in text
        assert "os.getenv" not in text


def test_relative_import_within_package_passes(tmp_path: Path) -> None:
    pkg = tmp_path / "domain"
    pkg.mkdir()
    (pkg / "rules.py").write_text("from .models import X\n")
    assert violations(pkg, set()) == []


def test_relative_import_of_sibling_package_flagged(tmp_path: Path) -> None:
    pkg = tmp_path / "domain"
    pkg.mkdir()
    (pkg / "rules.py").write_text("from ..storage import x\n")
    assert any("acme_agent.storage" in v for v in violations(pkg, set()))


def test_relative_bare_import_of_sibling_package_flagged(tmp_path: Path) -> None:
    pkg = tmp_path / "domain"
    pkg.mkdir()
    (pkg / "rules.py").write_text("from .. import storage\n")
    assert any("acme_agent.storage" in v for v in violations(pkg, set()))


def status_member_references(path: Path) -> list[int]:
    """Line numbers of `ScreeningStatus.<MEMBER>` attribute accesses (ADR-009.1)."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ScreeningStatus"
    ]


def test_only_rules_module_references_screening_status_members() -> None:
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC).as_posix() == "domain/rules.py":
            continue
        assert status_member_references(path) == [], path.name


def test_negative_case_detects_status_member_reference(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("status = ScreeningStatus.MEETS_REQUIREMENTS\n")
    assert status_member_references(bad) == [1]
