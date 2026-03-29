import hashlib
import os
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from sqlmodel import Session, select
from app.models.file_meta import FileMeta
from app.core.database import engine
from app.core.logger import global_logger as logger


def calculate_file_hash(file_path: str) -> str:
    """计算文件SHA256哈希值"""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"计算文件哈希失败 {file_path}: {e}")
        return ""

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, user_id: int, kb_id: int, kb_path: str):
        self.user_id = user_id
        self.kb_id = kb_id
        self.kb_path = kb_path
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return
        logger.info(f"文件创建: {event.src_path}")
        self._index_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        logger.info(f"文件修改: {event.src_path}")
        self._update_file(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        logger.info(f"文件删除: {event.src_path}")
        self._mark_deleted(event.src_path)

    def _index_file(self, file_path: str):
        """索引新文件"""
        try:
            path = Path(file_path)
            file_hash = calculate_file_hash(file_path)

            with Session(engine) as session:
                file_meta = FileMeta(
                    user_id=self.user_id,
                    kb_id=self.kb_id,
                    file_path=str(path.absolute()),
                    file_name=path.name,
                    file_type=path.suffix.lstrip('.'),
                    file_size=os.path.getsize(file_path),
                    parent_folder=str(path.parent.absolute()),
                    file_hash=file_hash
                )
                session.add(file_meta)
                session.commit()
                logger.info(f"文件已索引: {file_path}")
        except Exception as e:
            logger.error(f"索引文件失败 {file_path}: {e}")

    def _update_file(self, file_path: str):
        """更新文件索引"""
        try:
            file_hash = calculate_file_hash(file_path)

            with Session(engine) as session:
                statement = select(FileMeta).where(
                    FileMeta.file_path == file_path,
                    FileMeta.user_id == self.user_id
                )
                file_meta = session.exec(statement).first()

                if file_meta:
                    if file_meta.file_hash != file_hash:
                        file_meta.file_hash = file_hash
                        file_meta.file_size = os.path.getsize(file_path)
                        file_meta.modified_at = datetime.now()
                        file_meta.last_indexed_at = datetime.now()
                        session.add(file_meta)
                        session.commit()
                        logger.info(f"文件已更新: {file_path}")
                else:
                    self._index_file(file_path)
        except Exception as e:
            logger.error(f"更新文件失败 {file_path}: {e}")

    def _mark_deleted(self, file_path: str):
        """标记文件为已删除"""
        try:
            with Session(engine) as session:
                statement = select(FileMeta).where(
                    FileMeta.file_path == file_path,
                    FileMeta.user_id == self.user_id
                )
                file_meta = session.exec(statement).first()

                if file_meta:
                    file_meta.is_deleted = True
                    file_meta.modified_at = datetime.now()
                    session.add(file_meta)
                    session.commit()
                    logger.info(f"文件已标记删除: {file_path}")
        except Exception as e:
            logger.error(f"标记删除失败 {file_path}: {e}")


def start_file_watcher(kb_id: int, kb_path: str, user_id: int) -> Observer:
    """启动文件监听器"""
    if not os.path.exists(kb_path):
        raise FileNotFoundError(f"知识库路径不存在: {kb_path}")

    if not os.path.isdir(kb_path):
        raise NotADirectoryError(f"路径不是文件夹: {kb_path}")

    event_handler = FileChangeHandler(user_id, kb_id, kb_path)
    observer = Observer()
    observer.schedule(event_handler, kb_path, recursive=True)
    observer.start()
    logger.info(f"文件监听已启动: {kb_path}")
    return observer

