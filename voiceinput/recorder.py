"""兼容层：旧代码 ``voiceinput.recorder`` 现在指向新的音频模块。"""

from .audio import (  # noqa: F401
    TARGET_SR,
    AudioCapture,
    Recorder,
    has_voice,
    resample_to_16k,
    split_long_audio,
    trim_silence,
)
