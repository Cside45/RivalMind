"""Create reviewable source and WoW addon ZIP files; requires only Python stdlib."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent
VERSION = "0.2.0-alpha"


def write_zip(destination, files):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for file, archive_name in files:
            zipf.write(file, archive_name)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


addon_files = [(f, f.relative_to(ROOT / "addon").as_posix())
               for f in sorted((ROOT / "addon" / "RivalMind").rglob("*")) if f.is_file()]
source_files = [(f, f.relative_to(ROOT).as_posix())
                for f in sorted(ROOT.rglob("*"))
                if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts]

addon_zip = OUTPUT / f"RivalMind-addon-{VERSION}.zip"
source_zip = OUTPUT / f"RivalMind-starter-source-{VERSION}.zip"
addon_hash = write_zip(addon_zip, addon_files)
source_hash = write_zip(source_zip, source_files)
checksums = OUTPUT / f"RivalMind-SHA256SUMS-{VERSION}.txt"
checksums.write_text(f"{addon_hash}  {addon_zip.name}\n{source_hash}  {source_zip.name}\n")
print(addon_zip)
print(source_zip)
print(checksums)
