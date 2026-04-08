"""
EXECUTOR MODULE — 执行 Brain 的决策，原生浮动窗口实时展示给用户。

Brain 决定做什么 → Executor 真正做出来 → 原生窗口呈现给用户。
"""

from .executor import Executor
from .overlay import NativeOverlay

__all__ = ["Executor", "NativeOverlay"]
