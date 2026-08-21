"""Image Occlusion cards: masked labels on a diagram.

The note type turned out to be cheap. Anki has shipped a built-in Image
Occlusion notetype since 23.10, identified *only* by `originalStockKind == 6` —
never by name — and genanki can emit it with a small Model subclass. The client
supplies the masking JavaScript; we supply the shapes.

Coordinates are the expensive part, and they are why this needs its own
ingestion path. Anthropic's documentation is explicit that for PDF document
blocks the pages are rasterized server-side at dimensions the caller does not
control, so coordinates returned against them cannot be mapped back onto the
page. A diagram therefore has to be rasterized *here*, sent as an image block,
and the returned pixel coordinates normalised against the dimensions we chose.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from pathlib import Path

import genanki

# Anki identifies its Image Occlusion notetype by this stock kind alone. Get it
# wrong and the note imports as an ordinary cloze with visible shape text.
IMAGE_OCCLUSION_STOCK_KIND = 6

# The high-resolution tier: 2576px on the long edge, capped at 4784 visual
# tokens. Claude resizes server-side to fit these, so we resize to them first —
# otherwise the coordinates come back against dimensions we never saw.
MAX_EDGE_PX = 2576
PATCH = 28  # Images are billed in 28x28 patches.


@dataclass(frozen=True)
class Shape:
    """One mask, in the pixel space of the image we sent."""

    left: float
    top: float
    width: float
    height: float
    label: str = ""


def resized_dimensions(width: int, height: int) -> tuple[int, int]:
    """The size Claude will actually see, computed the way it computes it.

    Normalising against the original dimensions instead of these is the classic
    way to get masks that are subtly and consistently offset.
    """
    longest = max(width, height)
    if longest <= MAX_EDGE_PX:
        return width, height
    scale = MAX_EDGE_PX / longest
    return max(1, int(width * scale)), max(1, int(height * scale))


def visual_tokens(width: int, height: int) -> int:
    resized_width, resized_height = resized_dimensions(width, height)
    return math.ceil(resized_width / PATCH) * math.ceil(resized_height / PATCH)


def rasterize_pdf_page(pdf: Path, page_number: int, destination: Path, scale: float = 2.0) -> Path:
    """Render one page to PNG locally.

    Locally, because a page rasterized by the API comes back at dimensions we
    cannot know, and a mask drawn against unknown dimensions is a mask in the
    wrong place.
    """
    import pypdfium2

    document = pypdfium2.PdfDocument(str(pdf))
    try:
        page = document[page_number]
        image = page.render(scale=scale).to_pil()
        width, height = resized_dimensions(*image.size)
        image = image.resize((width, height))
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG")
    finally:
        document.close()
    return destination


def image_block(path: Path) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(path.read_bytes()).decode(),
        },
    }


SHAPES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["shapes"],
    "properties": {
        "shapes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["left", "top", "width", "height", "label"],
                "properties": {
                    # Absolute pixels, because Anthropic's guidance is explicit
                    # that asking for pre-normalised coordinates works badly.
                    # We normalise afterwards, where we know the dimensions.
                    "left": {"type": "integer", "description": "Left edge in pixels."},
                    "top": {"type": "integer", "description": "Top edge in pixels."},
                    "width": {"type": "integer", "description": "Width in pixels."},
                    "height": {"type": "integer", "description": "Height in pixels."},
                    "label": {"type": "string", "description": "What the mask hides."},
                },
            },
        }
    },
}

INSTRUCTION = (
    "Find every labelled part of this diagram that is worth learning.\n\n"
    "Return one rectangle per label, in ABSOLUTE PIXEL coordinates measured from "
    "the top-left of the image as given. Each rectangle should cover the label "
    "text itself, not the structure it points to, and should not overlap another.\n\n"
    "Skip titles, axis units, legends and figure numbers — they are not things "
    "to recall."
)


def build_shapes_request(image_path: Path) -> dict:
    from app import ingestion, planning

    return {
        "model": planning.MODEL,
        "max_tokens": 8000,
        "system": planning.SYSTEM,
        "output_config": {
            "effort": ingestion.EFFORT,
            "format": {"type": "json_schema", "schema": SHAPES_SCHEMA},
        },
        "messages": [
            {"role": "user", "content": [image_block(image_path), {"type": "text", "text": INSTRUCTION}]}
        ],
    }


def normalise_shapes(shapes: list[dict], width: int, height: int) -> list[Shape]:
    """Pixels to the 0–1 fractions Anki stores, clamped to the image."""
    out = []
    for shape in shapes:
        left = max(0.0, min(1.0, shape["left"] / width))
        top = max(0.0, min(1.0, shape["top"] / height))
        out.append(
            Shape(
                left=round(left, 4),
                top=round(top, 4),
                width=round(min(1.0 - left, shape["width"] / width), 4),
                height=round(min(1.0 - top, shape["height"] / height), 4),
                label=shape.get("label", ""),
            )
        )
    return out


def occlusion_text(shapes: list[Shape]) -> str:
    """Anki's shape encoding: one cloze per mask, carrying its geometry."""
    return "".join(
        "{{c%d::image-occlusion:rect:left=%.4f:top=%.4f:width=%.4f:height=%.4f}}"
        % (index, shape.left, shape.top, shape.width, shape.height)
        for index, shape in enumerate(shapes, start=1)
    )


class ImageOcclusionModel(genanki.Model):
    """genanki's Model, taught to declare itself as Anki's stock IO notetype.

    genanki emits a fixed notetype dict with no `originalStockKind`. Anki's
    schema-11 deserializer accepts the field, and looks for exactly that value
    to recognise an occlusion note — so injecting it is the whole adaptation.
    """

    def to_json(self, *args, **kwargs):
        rendered = super().to_json(*args, **kwargs)
        rendered["originalStockKind"] = IMAGE_OCCLUSION_STOCK_KIND
        return rendered


OCCLUSION_MODEL = ImageOcclusionModel(
    # Frozen, like the other two. A notetype id that changes between exports
    # makes every existing note conflicting on re-import.
    1651001200,
    "Image Occlusion (ai-anki)",
    fields=[{"name": "Occlusion"}, {"name": "Image"}, {"name": "Header"}, {"name": "Comments"}],
    templates=[
        {
            "name": "Image Occlusion",
            "qfmt": "{{#Header}}<div>{{Header}}</div>{{/Header}}\n"
            '<div style="display: none">{{cloze:Occlusion}}</div>\n'
            "<div id=io-wrapper><div id=io-overlay></div>"
            "<div id=io-original>{{Image}}</div></div>\n"
            "<script>anki.imageOcclusion.setup();</script>",
            "afmt": "{{#Header}}<div>{{Header}}</div>{{/Header}}\n"
            '<div style="display: none">{{cloze:Occlusion}}</div>\n'
            "<div id=io-wrapper><div id=io-overlay></div>"
            "<div id=io-original>{{Image}}</div></div>\n"
            "<script>anki.imageOcclusion.setup();</script>\n"
            "{{#Comments}}<div>{{Comments}}</div>{{/Comments}}",
        }
    ],
    model_type=genanki.Model.CLOZE,
    css="#io-overlay { position: absolute; top: 0; width: 100%; height: 100%; }\n"
    "#io-wrapper { position: relative; }\n"
    "#io-original { position: relative; }",
)
