import main
from src.api.app import app


def test_main_exposes_the_api_application() -> None:
    assert main.app is app
