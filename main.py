"""顶层入口：既可直接 ``python main.py`` 运行，也是 PyInstaller 打包的入口。

之所以单独放一个顶层脚本，是因为打包后 ``voiceinput/__main__.py`` 会被当成顶层
脚本执行，里面的相对导入（``from .app import ...``）会失败。
"""

from __future__ import annotations

from voiceinput.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
