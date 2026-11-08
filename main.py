"""Entry point of the watched-movie HTTP API: ``uvicorn main:app`` or ``python main.py``."""

from dotenv import load_dotenv

load_dotenv()

from src.api.app import app
from src.utils import flush_all_otel_loggers

__all__ = ["app"]

HOST = "0.0.0.0"
PORT = 10149


if __name__ == "__main__":
    # Flush ALL OTEL log handlers before starting uvicorn.
    # On Windows the BatchLogRecordProcessor's background HTTP export
    # can deadlock with ProactorEventLoop initialisation if both run
    # concurrently.  Every TracedLogger has its own BatchLogRecordProcessor;
    # we must drain them all.
    print("Flushing buffered OTEL log records before starting uvicorn.")
    flush_all_otel_loggers()

    print("Starting uvicorn server.")
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
