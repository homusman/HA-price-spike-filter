"""Build a deterministic HACS integration ZIP and checksum."""

import hashlib
import json
import zipfile
from pathlib import Path

source = Path("custom_components/price_spike_filter")
manifest = json.loads((source / "manifest.json").read_text())
assert manifest["domain"] == "price_spike_filter"
destination = Path("dist")
destination.mkdir(exist_ok=True)
archive = destination / "price_spike_filter.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        info = zipfile.ZipInfo(str(path.relative_to(source)).replace("\\", "/"), date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        output.writestr(info, path.read_bytes())
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
print(f"Packaged Price Spike Filter {manifest['version']}")
