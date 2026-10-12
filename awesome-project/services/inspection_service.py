import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models.inspection import Inspection
from schemas.requests.inspection import InspectionCreate

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "inspections"

MAX_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# SOF markers that carry the JPEG frame dimensions.
_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def _image_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    """Best-effort (width, height) by parsing the file header.

    Deliberately dependency-free: no Pillow in this environment. Handles PNG,
    GIF, WebP and JPEG; returns None for anything it cannot read, which simply
    leaves the dimension fields null.
    """
    if len(data) < 10:  # smallest header we read (GIF logical screen descriptor)
        return None

    # PNG: signature, chunk length, "IHDR", then width and height as big-endian.
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 \
            and data[12:16] == b"IHDR":
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )

    # GIF: "GIF87a"/"GIF89a" then little-endian dimensions.
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return (
            int.from_bytes(data[6:8], "little"),
            int.from_bytes(data[8:10], "little"),
        )

    # WebP: RIFF container, dimensions live in the first sub-chunk.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        if chunk == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
            return (
                (((b1 & 0x3F) << 8) | b0) + 1,
                (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6)) + 1,
            )
        return None

    # JPEG: walk the marker segments until a start-of-frame is found.
    if data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        while i + 3 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            if marker in _JPEG_SOF:
                return (
                    int.from_bytes(data[i + 7 : i + 9], "big"),  # width
                    int.from_bytes(data[i + 5 : i + 7], "big"),  # height
                )
            i += 2 + seg_len
    return None


def resolve_image_path(insp: Inspection) -> Path:
    return STORAGE_DIR / insp.image_filename


class InspectionService:
    def __init__(self, db: Session):
        self.db = db

    def get_inspection(self, inspection_id: int) -> Inspection | None:
        return (
            self.db.query(Inspection)
            .filter(Inspection.id == inspection_id)
            .first()
        )

    def get_inspections(
        self, skip: int = 0, limit: int = 100
    ) -> list[Inspection]:
        return (
            self.db.query(Inspection).offset(skip).limit(limit).all()
        )

    def create_inspection(
        self,
        data: InspectionCreate,
        *,
        original_name: str,
        content_type: str,
        content: bytes,
    ) -> Inspection:
        """Validate, persist the image to disk, and store the record."""
        if not content:
            raise ValueError("Uploaded file is empty")

        if len(content) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is too large "
                f"({len(content) // 1024 // 1024} MB, "
                f"limit {MAX_IMAGE_BYTES // 1024 // 1024} MB)"
            )

        extension = ALLOWED_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise ValueError(
                f"Unsupported image type '{content_type}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            )

        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        (STORAGE_DIR / filename).write_bytes(content)

        dims = _image_dimensions(content)
        insp = Inspection(
            **data.model_dump(),
            image_filename=filename,
            image_original_name=(original_name or filename)[:255],
            image_content_type=content_type,
            image_size_bytes=len(content),
            image_width=dims[0] if dims else None,
            image_height=dims[1] if dims else None,
        )
        self.db.add(insp)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            (STORAGE_DIR / filename).unlink(missing_ok=True)
            raise
        self.db.refresh(insp)
        return insp

    def delete_inspection(self, inspection_id: int) -> bool:
        insp = self.get_inspection(inspection_id)
        if not insp:
            return False
        path = resolve_image_path(insp)
        self.db.delete(insp)
        self.db.commit()
        path.unlink(missing_ok=True)
        return True