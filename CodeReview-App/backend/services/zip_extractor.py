import zipfile
import io
import os

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_XAML_SIZE = 2 * 1024 * 1024  # 2 MB per file


def extract_xaml_from_zip(zip_bytes: bytes, zip_filename: str) -> dict:
    """
    Extract .xaml files from a ZIP archive.

    Returns:
      {
        "files": [{"file_name": str, "zip_entry_path": str, "content": str, "size_bytes": int}],
        "skipped_files": [str],
        "total_entries_scanned": int,
      }
    """
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError(
            f"ZIP file '{zip_filename}' is {len(zip_bytes) / (1024 * 1024):.1f} MB, "
            f"exceeding the {MAX_ZIP_SIZE // (1024 * 1024)} MB limit."
        )

    files: list[dict] = []
    skipped_files: list[str] = []
    total_entries_scanned = 0
    project_json_content: str | None = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for entry in zf.infolist():
            total_entries_scanned += 1

            if entry.is_dir():
                continue
            if entry.filename.startswith("__MACOSX/"):
                continue

            # Extract project.json if present
            if os.path.basename(entry.filename).lower() == "project.json":
                raw = zf.read(entry.filename)
                project_json_content = raw.decode("utf-8", errors="replace")
                continue

            if not entry.filename.lower().endswith(".xaml"):
                continue

            raw = zf.read(entry.filename)
            if len(raw) > MAX_XAML_SIZE:
                skipped_files.append(entry.filename)
                continue

            content = raw.decode("utf-8", errors="replace")
            files.append(
                {
                    "file_name": os.path.basename(entry.filename),
                    "zip_entry_path": entry.filename,
                    "content": content,
                    "size_bytes": len(raw),
                }
            )

    return {
        "files": files,
        "skipped_files": skipped_files,
        "total_entries_scanned": total_entries_scanned,
        "project_json": project_json_content,
    }
