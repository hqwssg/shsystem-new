import _bootstrap  # noqa: F401
import uvicorn
from carbon_prediction.config import settings

if __name__ == "__main__":
    uvicorn.run("carbon_prediction.api:app", host=settings.api_host, port=settings.api_port,
                reload=False, log_level="info")
