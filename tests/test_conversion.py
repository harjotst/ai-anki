"""The remaining input formats.

The concurrency assertion here is the important one. Six conversions sharing a
LibreOffice user profile do not queue — they fail, silently, with no diagnostic
output whatsoever. That is a correctness bug that looks like flakiness, so it is
pinned by a test rather than left to a comment.
"""

import shutil
from pathlib import Path

import pytest

from app import conversion

soffice_available = pytest.mark.skipif(
    shutil.which(conversion.SOFFICE) is None,
    reason="LibreOffice is only present in the container image",
)


def spreadsheet(path: Path) -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Enzymes"
    sheet.append(["Enzyme", "Substrate", "Km"])
    sheet.append(["Hexokinase", "Glucose", "0.1"])
    sheet.append(["PFK-1", "F6P", "0.03"])
    workbook.save(path)
    return path


def test_a_spreadsheet_is_read_as_tables_not_rendered_as_pages(tmp_path):
    markdown = conversion.spreadsheet_to_markdown(spreadsheet(tmp_path / "kinetics.xlsx"))

    assert "## Enzymes" in markdown
    assert "| Enzyme | Substrate | Km |" in markdown
    assert "| Hexokinase | Glucose | 0.1 |" in markdown
    # As text it is billed once. Rendered to a page it would be billed as
    # extracted text *and* an image, and read worse.
    assert "<" not in markdown


def test_the_conversion_concurrency_limit_is_sized_to_processors_not_to_the_fan_out():
    from app import generation  # noqa: F401  (imported to show they are unrelated)

    assert 1 <= conversion.MAX_CONCURRENT <= 4
    # On one vCPU, parallel conversion buys nothing (measured 2922ms for one,
    # 12280ms for four) and multiplies a ~218MB peak until the machine OOMs.
    assert conversion.MAX_CONCURRENT <= max(1, __import__("os").cpu_count() or 1)


def test_formats_are_routed_by_what_they_are():
    assert conversion.needs_conversion(Path("lecture.pptx"))
    assert conversion.needs_conversion(Path("notes.docx"))
    assert not conversion.needs_conversion(Path("scan.pdf"))
    assert conversion.is_spreadsheet(Path("kinetics.xlsx"))
    assert conversion.is_image(Path("diagram.png"))


def test_a_missing_output_names_the_file_that_failed(tmp_path, monkeypatch):
    """A user with six files needs to know which one to remove."""
    # Exits 0 and writes nothing — the exact shape of the silent failure.
    monkeypatch.setattr(conversion, "SOFFICE", shutil.which("true"))
    source = tmp_path / "broken-slides.pptx"
    source.write_bytes(b"not really a pptx")

    with pytest.raises(conversion.ConversionFailed) as raised:
        conversion.convert_to_pdf(source, tmp_path / "out")

    assert "broken-slides.pptx" in str(raised.value)


def test_the_output_file_is_what_is_trusted_not_the_exit_code(tmp_path, monkeypatch):
    # LibreOffice can exit 0 having produced nothing, and can fail having said
    # nothing. Only the artefact is evidence.
    monkeypatch.setattr(conversion, "SOFFICE", shutil.which("true"))
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"x")

    with pytest.raises(conversion.ConversionFailed):
        conversion.convert_to_pdf(source, tmp_path / "out")


@soffice_available
def test_a_real_document_converts_to_a_real_pdf(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Glycolysis occurs in the cytosol.\n" * 40)

    produced = conversion.convert_to_pdf(source, tmp_path / "out")

    assert produced.exists()
    assert produced.read_bytes().startswith(b"%PDF")


@soffice_available
async def test_a_concurrent_batch_produces_every_output(tmp_path):
    """The regression guard for the silent-failure case.

    With a shared profile this produces a couple of PDFs and several bare
    exit-1s with no output. With a fresh profile per invocation it produces all
    of them.
    """
    sources = []
    for index in range(6):
        source = tmp_path / f"doc-{index}.txt"
        source.write_text(f"Document {index}\n" * 50)
        sources.append(source)

    produced = await conversion.convert_many(sources, tmp_path / "out")

    assert len(produced) == 6
    assert all(path.exists() and path.read_bytes().startswith(b"%PDF") for path in produced)
