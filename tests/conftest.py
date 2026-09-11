import pytest


@pytest.fixture(autouse=True)
def _no_real_alignment(monkeypatch):
    """默认关掉强制对齐。

    它要加载一个几百兆的声学模型，测试套件不该依赖那个下载；
    对齐本身的逻辑在 test_align.py 里单独测。
    """
    from shadow.analysis import align

    monkeypatch.setattr(align, "available", lambda: False)
