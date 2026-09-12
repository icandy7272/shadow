"""网页导入：记录马上建好，下载、转写、切句在后台线程里跑。同一时间只导入一份。

跑在服务进程里：关掉终端或改代码触发自动重载，线程就没了。
服务再启动时会把卡在半路的记录标成「导入被中断」，点重试即可。
"""

from __future__ import annotations

import logging
import threading

from .. import db, library
from ..ingest import pipeline

log = logging.getLogger(__name__)
_lock = threading.Lock()


class Busy(RuntimeError):
    """上一份还在导入。"""


class NotRetryable(RuntimeError):
    """只有导入失败的素材能重试。"""


def _connect():
    """各开各的连接（sqlite 连接不能跨线程）；表不在就先建好，全新的数据目录也能直接导入。"""
    connection = db.connect()
    db.init_db(connection)
    return connection


def _run(source_id: int) -> None:
    connection = _connect()
    try:
        pipeline.run_import(source_id, conn=connection)
    except Exception:
        # 错误已经由 run_import 记进 sources.error，线程里再抛也没人接
        log.exception("素材 %s 导入失败", source_id)
    finally:
        connection.close()


def _in_background(source_id: int) -> None:
    threading.Thread(target=_run, args=(source_id,), daemon=True,
                     name=f"import-{source_id}").start()


def start(url: str, *, launch=None) -> int:
    """建记录、交给后台，立刻返回素材号。链接格式不对抛 DownloadError。"""
    # 默认值在运行时解析：测试要能换掉 _in_background
    launch = launch or _in_background
    with _lock:
        connection = _connect()
        try:
            if db.importing_source(connection) is not None:
                raise Busy("上一份还在导入，等它完成再导入下一份。")
            source_id = pipeline.begin_import(url, conn=connection)
        finally:
            connection.close()
    launch(source_id)
    return source_id


def retry(source_id: int, *, launch=None) -> int:
    """用原链接重新导入，删掉失败的那条。"""
    connection = _connect()
    try:
        row = db.get_source(connection, source_id)
        if row is None or row["status"] != db.STATUS_FAILED:
            raise NotRetryable("只有导入失败的素材能重试。")
        url = row["url"]
        library.remove(connection, source_id)
    finally:
        connection.close()
    return start(url, launch=launch)
