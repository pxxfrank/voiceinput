"""把打包目录压缩为 Portable ZIP（支持 >2GB，附加 portable.flag）。"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

LARGE_SUFFIX = {".exe", ".dll", ".onnx", ".gguf", ".wav", ".pyd"}


def build(src: Path, out: Path, flag_name: str = "portable.flag") -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    files = [p for p in src.rglob("*") if p.is_file()]
    total = len(files)
    with zipfile.ZipFile(out, "w", allowZip64=True) as zf:
        for i, path in enumerate(files, 1):
            rel = path.relative_to(src).as_posix()
            compress = zipfile.ZIP_STORED if path.suffix.lower() in LARGE_SUFFIX else zipfile.ZIP_DEFLATED
            zf.write(path, rel, compress_type=compress)
            if i % 200 == 0 or i == total:
                print(f"  {i}/{total}")
        zf.writestr(flag_name, "1")
    print(f"已生成 {out}（{out.stat().st_size / 1048576:.1f} MB）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("out")
    args = parser.parse_args()
    return build(Path(args.src), Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
