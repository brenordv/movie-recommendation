import traceback
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel

from src.letterboxd.movie_importer.movie_importer import import_movie, ImportResult
from src.utils import get_otel_log_handler


class WatchedMovieRequest(BaseModel):
    title: str
    watch_date: datetime
    year: int
    letterboxd_uri: str

app = FastAPI(
    title="Watched Movie API",
    description="API for importing watched movies to the movie recommendation system.",
    version="1.0.0"
)

logger = get_otel_log_handler("API", fastapi_app=app)


@logger.trace("_is_request_valid")
def _is_request_valid(item: WatchedMovieRequest) -> bool:
    return (
            item is not None
            and item.title is not None
            and item.title.strip() != ""
            and item.watch_date is not None
            and item.year is not None
            and 1900 < item.year < 2100
            and item.letterboxd_uri is not None
            and item.letterboxd_uri.strip() != ""
    )

@app.post("/api/watched")
@logger.trace("/api/watched")
async def watched(
        item: WatchedMovieRequest,
        request: Request):
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes({
            "http.method": request.method,
            "http.client_ip": request.client.host,
            "media.title": item.title,
            "media.year": item.year,
            "media.letterboxd_uri": item.letterboxd_uri,
        })

    if not _is_request_valid(item):
        raise HTTPException(status_code=400, detail=f"Invalid request: {item}")

    client_ip = request.client.host

    logger.info(f"Received request from {client_ip}: {item}")

    return_data = {
        "title": item.title,
        "year": item.year,
    }

    try:
        logger.info(f"Processing request for movie: {item.title} ({item.year})")

        result = import_movie(
            letterboxd_uri=item.letterboxd_uri,
            watch_date=item.watch_date,
            title=item.title,
            year=item.year,
        )

        if result == ImportResult.SUCCESS:
            logger.info(f"Successfully processed request for movie: {item.title} ({item.year})")
            return JSONResponse(status_code=status.HTTP_201_CREATED, content={"result": "success", "data": return_data})
        elif result == ImportResult.ALREADY_EXISTS:
            logger.info(f"Movie already exists in database: {item.title} ({item.year})")
            return JSONResponse(status_code=status.HTTP_200_OK, content={"result": "already_exists", "data": return_data})
        else:
            logger.error(f"Error processing request for movie: {item.title} ({item.year})")
            return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"result": "error", "data": return_data})

    except Exception as e:
        logger.error(f"Error processing request for movie: {item.title} ({item.year}): {e}")
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"result": "error", "data": return_data, "error": str(e)})


@app.get("/api/health")
#@logger.trace("/api/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        200 with a "healthy" message if the service is running
        500 with a "broken" message if any error occurs
    """
    try:
        return JSONResponse(content={"message": "healthy"}, status_code=200)
    except Exception as e:
        error_detail = f"Health check failed: {str(e)}"
        traceback.print_exc()
        return JSONResponse(content={"message": "broken", "error": error_detail}, status_code=500)
