from __future__ import annotations

import datetime
import logging
import logging.handlers
import os


def _resolve_log_path(log_file: str) -> str:
    """날짜 플레이스홀더가 있는 로그 경로를 실제 경로로 변환한다."""
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    return log_file.format(date=date_str) if "{date}" in log_file else log_file


def _safe_makedirs(path: str) -> None:
    """로그 파일 부모 디렉터리를 생성한다."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def configure_logging(
    log_file: str,
    log_level: str,
    simple_enabled: bool = False,
    simple_level: str = "WARNING",
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """파일/콘솔 로그를 설정한다."""
    log_path = _resolve_log_path(log_file)
    _safe_makedirs(log_path)

    logger = logging.getLogger("kw-bot")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    file_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    if simple_enabled:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max(1, int(max_bytes)),
            backupCount=max(0, int(backup_count)),
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, str(simple_level).upper(), logging.WARNING))
    else:
        if "{date}" in log_file:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        else:
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_path, when="midnight", interval=1, backupCount=14, encoding="utf-8"
            )
            file_handler.suffix = "%Y%m%d"
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def configure_trade_logger(
    log_file: str,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """당일 매매 로그 전용 로거를 설정한다."""
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    log_path = log_file.format(date=date_str) if "{date}" in log_file else log_file
    _safe_makedirs(log_path)

    logger = logging.getLogger("kw-trades")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(0, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def configure_chejan_logger(
    log_dir: str,
    enabled: bool = True,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """CHEJAN 원본 이벤트 전용 로그를 설정한다."""
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = os.path.join(log_dir, f"chejan_{date_str}.log")
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    logger = logging.getLogger("kw-chejan")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    if not enabled:
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return logger

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        filename,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(0, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger
