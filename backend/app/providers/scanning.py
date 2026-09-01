"""File validation and malware scanning.

Two layers, both real:

1. **Structural validation** - magic-byte check, size limit, extension/content-type
   agreement, and format-specific danger signals (embedded JavaScript or launch actions
   in a PDF, macro streams in an OOXML container). This runs always.
2. **Anti-virus** - a real ClamAV daemon when ``MALWARE_SCANNER=clamav``.

When ClamAV is not configured the verdict is reported as ``NOT_SCANNED`` rather than
``CLEAN``: an unscanned file must never be labelled as having passed a scan.
"""

from __future__ import annotations

import asyncio
import re
import struct
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
from io import BytesIO
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import FileTooLarge, UnsupportedFileType
from app.core.logging import get_logger

logger = get_logger(__name__)


class ScanVerdict(StrEnum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    #: Structural checks passed but no AV engine was available.
    NOT_SCANNED = "NOT_SCANNED"
    #: Structural checks found something a human should look at.
    SUSPICIOUS = "SUSPICIOUS"
    ERROR = "ERROR"


@dataclass(slots=True)
class ScanResult:
    verdict: ScanVerdict
    engine: str
    detail: str | None = None
    findings: list[str] = field(default_factory=list)

    @property
    def is_safe_to_store(self) -> bool:
        return self.verdict in (ScanVerdict.CLEAN, ScanVerdict.NOT_SCANNED)


#: Leading magic bytes by extension. A file whose content contradicts its name is
#: rejected before anything else touches it.
MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}

CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

#: PDF constructs that execute or fetch on open. Legitimate resumes never need these.
_PDF_DANGER = (
    (b"/JavaScript", "PDF contains JavaScript"),
    (b"/JS", "PDF contains a JavaScript action"),
    (b"/Launch", "PDF contains a launch action"),
    (b"/EmbeddedFile", "PDF contains an embedded file"),
    (b"/OpenAction", "PDF runs an action on open"),
    (b"/AA", "PDF has additional (automatic) actions"),
)

_OOXML_MACRO_PARTS = re.compile(r"(vbaProject\.bin|vbaData\.xml|macros/)", re.IGNORECASE)

#: EICAR test signature - a real detection any scanner must catch, useful in tests.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def validate_upload(
    *, filename: str, content: bytes, allowed_extensions: set[str], max_size_mb: int
) -> tuple[str, str]:
    """Validate size, extension and magic bytes. Returns ``(extension, content_type)``."""
    if not content:
        raise UnsupportedFileType("The uploaded file is empty")

    max_bytes = max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise FileTooLarge(
            f"File is {len(content) / 1024 / 1024:.1f} MB; the limit is {max_size_mb} MB"
        )

    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in allowed_extensions:
        raise UnsupportedFileType(
            f"'.{extension}' files are not accepted. Allowed: "
            f"{', '.join(sorted(f'.{e}' for e in allowed_extensions))}"
        )

    signatures = MAGIC_SIGNATURES.get(extension)
    if signatures and not any(content.startswith(sig) for sig in signatures):
        raise UnsupportedFileType(
            f"The file content does not look like a valid .{extension} file"
        )

    return extension, CONTENT_TYPES.get(extension, "application/octet-stream")


def inspect_structure(content: bytes, extension: str) -> list[str]:
    """Format-aware danger signals. Returns human-readable findings (empty = nothing found)."""
    findings: list[str] = []

    if extension == "pdf":
        for marker, description in _PDF_DANGER:
            if marker in content:
                findings.append(description)
        # A PDF claiming a huge object count with a tiny body is a classic malformed-file
        # denial-of-service shape.
        if content.count(b" obj") > 50_000:
            findings.append("PDF declares an implausible number of objects")

    elif extension in ("docx", "doc"):
        if extension == "docx":
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    names = archive.namelist()
                    if any(_OOXML_MACRO_PARTS.search(n) for n in names):
                        findings.append("Document contains a macro project")
                    if any(n.startswith("/") or ".." in n for n in names):
                        findings.append("Document archive contains unsafe entry paths")
                    # Zip-bomb heuristic: refuse absurd compression ratios.
                    total = sum(info.file_size for info in archive.infolist())
                    if len(content) and total / len(content) > 200:
                        findings.append("Document expands to a disproportionate size")
            except zipfile.BadZipFile:
                findings.append("Document is not a readable OOXML container")
        elif b"\x00Macros" in content or b"VBA" in content:
            findings.append("Legacy document appears to contain macros")

    if EICAR in content:
        findings.append("EICAR anti-virus test signature detected")

    return findings


class MalwareScanner:
    """Structural scanner, optionally backed by a real ClamAV daemon."""

    def __init__(self) -> None:
        self.use_clamav = settings.MALWARE_SCANNER == "clamav"

    async def scan(self, content: bytes, *, extension: str) -> ScanResult:
        findings = inspect_structure(content, extension)

        if self.use_clamav:
            av = await self._scan_clamav(content)
            if av.verdict == ScanVerdict.INFECTED:
                av.findings = findings + av.findings
                return av
            if av.verdict == ScanVerdict.ERROR:
                # An AV outage must not be reported as a clean file.
                return ScanResult(
                    verdict=ScanVerdict.ERROR,
                    engine="clamav",
                    detail=av.detail,
                    findings=findings,
                )
            if findings:
                return ScanResult(
                    verdict=ScanVerdict.SUSPICIOUS,
                    engine="clamav+structural",
                    detail="; ".join(findings),
                    findings=findings,
                )
            return ScanResult(verdict=ScanVerdict.CLEAN, engine="clamav+structural")

        if findings:
            return ScanResult(
                verdict=ScanVerdict.SUSPICIOUS,
                engine="structural",
                detail="; ".join(findings),
                findings=findings,
            )
        return ScanResult(
            verdict=ScanVerdict.NOT_SCANNED,
            engine="structural",
            detail=(
                "Structural checks passed. No anti-virus engine is configured, so this "
                "file has not been scanned for malware."
            ),
        )

    async def _scan_clamav(self, content: bytes) -> ScanResult:
        """Talk INSTREAM to clamd."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=10
            )
        except (TimeoutError, OSError) as exc:
            logger.warning("clamav_unreachable", error=str(exc))
            return ScanResult(
                verdict=ScanVerdict.ERROR, engine="clamav", detail=f"clamd unreachable: {exc}"
            )

        try:
            writer.write(b"zINSTREAM\x00")
            chunk_size = 8192
            for offset in range(0, len(content), chunk_size):
                chunk = content[offset : offset + chunk_size]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
            writer.write(struct.pack("!L", 0))
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(4096), timeout=60)
        except (TimeoutError, OSError) as exc:
            return ScanResult(
                verdict=ScanVerdict.ERROR, engine="clamav", detail=f"clamd error: {exc}"
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

        response = raw.decode("utf-8", errors="replace").strip("\x00 \n")
        if response.endswith("OK"):
            return ScanResult(verdict=ScanVerdict.CLEAN, engine="clamav")
        if "FOUND" in response:
            signature = response.split(":", 1)[-1].replace("FOUND", "").strip()
            return ScanResult(
                verdict=ScanVerdict.INFECTED,
                engine="clamav",
                detail=f"Malware detected: {signature}",
                findings=[signature],
            )
        return ScanResult(verdict=ScanVerdict.ERROR, engine="clamav", detail=response[:200])


_scanner: MalwareScanner | None = None


def get_scanner() -> MalwareScanner:
    global _scanner
    if _scanner is None:
        _scanner = MalwareScanner()
    return _scanner


def reset_scanner() -> None:
    global _scanner
    _scanner = None
