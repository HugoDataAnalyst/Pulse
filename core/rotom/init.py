from utils.http_api import APIClient
import config as AppConfig

def get_rotom_client() -> APIClient:
    """
    Builds an APIClient using ROTOM* envs.
    - ROTOM_API_BASE_URL (required)
    """
    base = AppConfig.ROTOM_API_BASE_URL or ""
    username = None
    password = None
    bearer = None
    secret = None
    return APIClient(base, username=username, password=password, bearer=bearer, secret=secret)
