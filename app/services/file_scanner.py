import os
from pathlib import Path
from sqlmodel import Session
from app.models.file_meta import FileMeta
from app.services.file_watcher import calculate_file_hash
from app.core.logger import global_logger as logger


def scan_directory(kb_id: int, kb_path: str, user_id: int, session: Session):
    """扫描目录并索引所有文件"""
    if not os.path.exists(kb_path):
        raise FileNotFoundError(f"路径不存在: {kb_path}")

    if not os.path.isdir(kb_path):
        raise NotADirectoryError(f"不是文件夹: {kb_path}")

    indexed_count = 0

    for root, dirs, files in os.walk(kb_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                path = Path(file_path)
                file_hash = calculate_file_hash(file_path)

                file_meta = FileMeta(
                    user_id=user_id,
                    kb_id=kb_id,
                    file_path=str(path.absolute()),
                    file_name=path.name,
                    file_type=path.suffix.lstrip('.'),
                    file_size=os.path.getsize(file_path),
                    parent_folder=str(path.parent.absolute()),
                    file_hash=file_hash
                )
                session.add(file_meta)
                indexed_count += 1
            except Exception as e:
                logger.error(f"索引文件失败 {file_path}: {e}")

    session.commit()
    logger.info(f"扫描完成,共索引 {indexed_count} 个文件")
    return indexed_count
