"""Masked-label cards for diagrams.

The note type is stock and cheap. The coordinates are the expensive part, and
they are why this has its own ingestion path: Anthropic's documentation states
that PDF pages are rasterized server-side at dimensions the caller does not
control, so coordinates returned against a PDF block cannot be mapped back onto
the page. Everything here rasterizes locally first.
"""

import genanki
import pytest

from app import occlusion
from app.jobs import Card
from tests.anki_harness import anki_collection


def test_the_image_is_resized_the_way_the_api_will_resize_it():
    # Normalising against the original size instead of this is how masks end up
    # subtly and consistently offset.
    assert occlusion.resized_dimensions(1000, 800) == (1000, 800)
    wide = occlusion.resized_dimensions(5152, 2576)
    assert max(wide) == occlusion.MAX_EDGE_PX
    assert wide == (2576, 1288), "aspect ratio is preserved"


def test_a_full_size_image_stays_inside_the_visual_token_cap():
    assert occlusion.visual_tokens(5152, 2576) <= 4784


def test_coordinates_are_requested_in_pixels_not_pre_normalised(tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    request = occlusion.build_shapes_request(image)

    instruction = request["messages"][0]["content"][-1]["text"]
    assert "ABSOLUTE PIXEL" in instruction
    # Asking for pre-normalised coordinates is documented as working badly; we
    # normalise ourselves, where the dimensions are known.
    assert "0 and 1000" not in instruction
    assert request["messages"][0]["content"][0]["type"] == "image"


def test_pixels_become_fractions_against_the_size_we_actually_sent():
    shapes = occlusion.normalise_shapes(
        [{"left": 250, "top": 100, "width": 200, "height": 50, "label": "nucleus"}],
        width=1000,
        height=500,
    )

    assert shapes[0].left == 0.25
    assert shapes[0].top == 0.2
    assert shapes[0].width == 0.2
    assert shapes[0].height == 0.1


def test_a_mask_that_runs_off_the_image_is_clamped_rather_than_emitted_broken():
    shapes = occlusion.normalise_shapes(
        [{"left": 900, "top": 0, "width": 400, "height": 100, "label": "edge"}],
        width=1000,
        height=500,
    )

    assert shapes[0].left + shapes[0].width <= 1.0


def test_each_shape_becomes_its_own_cloze_so_anki_makes_one_card_each():
    text = occlusion.occlusion_text(
        [
            occlusion.Shape(0.1, 0.1, 0.2, 0.1, "a"),
            occlusion.Shape(0.5, 0.5, 0.2, 0.1, "b"),
        ]
    )

    assert "{{c1::image-occlusion:rect:" in text
    assert "{{c2::image-occlusion:rect:" in text


def test_the_notetype_declares_the_stock_kind_anki_recognises_it_by():
    rendered = occlusion.OCCLUSION_MODEL.to_json(0, 0)

    # Anki identifies an occlusion notetype by this and never by name. Without
    # it the note imports as an ordinary cloze showing raw shape text.
    assert rendered["originalStockKind"] == occlusion.IMAGE_OCCLUSION_STOCK_KIND
    assert [field["name"] for field in occlusion.OCCLUSION_MODEL.fields][:2] == [
        "Occlusion",
        "Image",
    ]


def test_a_real_collection_accepts_the_note_and_makes_one_card_per_mask(tmp_path):
    """The claim the whole ticket rests on, checked in Anki rather than assumed."""
    image = tmp_path / "diagram.png"
    # A 1x1 PNG is enough: Anki stores the media, it does not decode it here.
    image.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a49444154789c63000100000500010d0a2db40000"
            "000049454e44ae426082"
        )
    )
    shapes = [
        occlusion.Shape(0.20, 0.30, 0.15, 0.08, "nucleus"),
        occlusion.Shape(0.55, 0.60, 0.18, 0.09, "mitochondrion"),
    ]

    deck = genanki.Deck(1651001201, "AI Anki::Diagrams")
    deck.add_note(
        genanki.Note(
            model=occlusion.OCCLUSION_MODEL,
            fields=[
                occlusion.occlusion_text(shapes),
                f'<img src="{image.name}">',
                "Cell diagram",
                "",
            ],
            guid="occlusion-1",
        )
    )
    package_path = tmp_path / "occlusion.apkg"
    genanki.Package(deck, media_files=[str(image)]).write_to_file(str(package_path))

    with anki_collection() as col:
        col.import_package(package_path.read_bytes())

        note = col.note("occlusion-1")
        assert note is not None
        # Two masks, two cards — the model generates one per cloze ordinal.
        assert note.card_count == 2
        assert "AI Anki::Diagrams" in col.decks


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_a_pdf_page_rasterizes_locally_to_a_png_within_the_tier_bounds(tmp_path, scale):
    pytest.importorskip("pypdfium2")
    import pypdfium2  # noqa: F401

    from app import conversion

    source = tmp_path / "notes.txt"
    source.write_text("A diagram would go here.\n" * 30)
    try:
        pdf = conversion.convert_to_pdf(source, tmp_path / "out")
    except (conversion.ConversionFailed, FileNotFoundError):
        pytest.skip("LibreOffice is only present in the container image")

    png = occlusion.rasterize_pdf_page(pdf, 0, tmp_path / "page.png", scale=scale)

    assert png.read_bytes().startswith(b"\x89PNG")
    from PIL import Image

    with Image.open(png) as image:
        assert max(image.size) <= occlusion.MAX_EDGE_PX
