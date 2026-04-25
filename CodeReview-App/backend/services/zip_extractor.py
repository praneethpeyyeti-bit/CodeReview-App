import zipfile
import io
import os

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_XAML_SIZE = 2 * 1024 * 1024  # 2 MB per file


def extract_xaml_from_zip(zip_bytes: bytes, zip_filename: str) -> dict:
    """
    Extract a UiPath project ZIP archive.

    The XAML files are decoded to text so the reviewer/fixer can operate on
    them. Every other archive entry (project.json, .cs, .nuspec, Test_Data,
    Screenshots, .entities/, assets, etc.) is retained as raw bytes under
    ``other_files`` so the full project folder structure can be reconstructed
    on disk when the user accepts fixes.

    Returns:
      {
        "files": [{"file_name": str, "zip_entry_path": str, "content": str, "size_bytes": int}],
        "skipped_files": [str],
        "total_entries_scanned": int,
        "project_json": str | None,
        "other_files": [{"zip_entry_path": str, "content_bytes": bytes}],
      }
    """
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError(
            f"ZIP file '{zip_filename}' is {len(zip_bytes) / (1024 * 1024):.1f} MB, "
            f"exceeding the {MAX_ZIP_SIZE // (1024 * 1024)} MB limit."
        )

    files: list[dict] = []
    other_files: list[dict] = []
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

            raw = zf.read(entry.filename)

            # project.json is also kept as text for dependency lookup / write-back.
            if os.path.basename(entry.filename).lower() == "project.json":
                project_json_content = raw.decode("utf-8", errors="replace")
                other_files.append(
                    {"zip_entry_path": entry.filename, "content_bytes": raw}
                )
                continue

            if entry.filename.lower().endswith(".xaml"):
                if len(raw) > MAX_XAML_SIZE:
                    skipped_files.append(entry.filename)
                    # Oversize XAML still flows through passthrough so it
                    # doesn't disappear from the output folder.
                    other_files.append(
                        {"zip_entry_path": entry.filename, "content_bytes": raw}
                    )
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
                continue

            # Everything else (assets, .cs, Test_Data, Screenshots, …) is
            # passed through verbatim.
            other_files.append(
                {"zip_entry_path": entry.filename, "content_bytes": raw}
            )

    return {
        "files": files,
        "skipped_files": skipped_files,
        "total_entries_scanned": total_entries_scanned,
        "project_json": project_json_content,
        "other_files": other_files,
    }
