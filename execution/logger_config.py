import logging
import os
from datetime import datetime

def setup_logger(name: str):
    """
    Configures and returns a logger with the specified name.
    Logs to both console and a file in the logs/ directory.
    """
    if not os.path.exists("logs"):
        os.makedirs("logs")

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if logger is already initialized
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File Handler (Persistent)
        log_filename = "logs/system.log"
        file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Add a separator to clarify new run start
        logger.info(f"{'='*30} NEW RUN SESSION STARTED {'='*30}")

    return logger
