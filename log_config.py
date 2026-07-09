import logging

def setup_logging():
    """Set up advanced logging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('app.log'),
            logging.StreamHandler()
        ]
    )

    # Add specific loggers if needed
    logger = logging.getLogger('WLED_ambient_lighting')
    return logger
