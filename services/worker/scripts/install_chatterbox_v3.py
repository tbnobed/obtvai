"""Install the official Spanish V3 runtime without replacing the legacy package.

The official language-pack demo carries the matching V3 decoder; the PyPI
package and even the GitHub V3 selector still use the older decoder.
Only library code is copied: no Gradio UI or additional dependency resolver.
"""
from pathlib import Path
import shutil
import tempfile
import urllib.request

from huggingface_hub import snapshot_download

SOURCE_REPO = "ResembleAI/Chatterbox-Multilingual-TTS-es-mx-latam"
SOURCE_REVISION = "0d2648c4c1637eccfa8d45c7e192a0ad8d5b1fca"
LICENSE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"


def main():
    target = Path("/opt/chatterbox-v3/chatterbox_v3")
    with tempfile.TemporaryDirectory(prefix="chatterbox-v3-source-") as tmp:
        source = Path(snapshot_download(
            repo_id=SOURCE_REPO,
            repo_type="space",
            revision=SOURCE_REVISION,
            allow_patterns=["chatterbox/src/chatterbox/*.py", "chatterbox/src/chatterbox/**/*.py"],
            local_dir=tmp,
        )) / "chatterbox/src/chatterbox"
        if not (source / "tts.py").is_file():
            raise RuntimeError("Pinned Chatterbox V3 source is incomplete")
        shutil.copytree(source, target)
    with urllib.request.urlopen(
        f"https://raw.githubusercontent.com/resemble-ai/chatterbox/{LICENSE_REVISION}/LICENSE",
        timeout=60,
    ) as response:
        license_text = response.read()
    if b"MIT License" not in license_text:
        raise RuntimeError("Expected upstream MIT license")
    (target / "LICENSE").write_bytes(license_text)
    (target / "SOURCE.txt").write_text(
        f"https://huggingface.co/spaces/{SOURCE_REPO}/tree/{SOURCE_REVISION}\n"
        "Unmodified library source; installed in a separate Python namespace.\n"
    )


if __name__ == "__main__":
    main()