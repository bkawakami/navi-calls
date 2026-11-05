"""Entry point FastAPI: lifespan (MongoDB, índices, polling de status) e registro de routers."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.models import ensure_indexes

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _status_poller(app: FastAPI):
    """Fallback aos webhooks: consulta periodicamente o status dos bots ativos na Recall."""
    from app.services.meeting_service import get_meeting_service

    if not settings.RECALL_API_KEY:
        logger.warning("RECALL_API_KEY ausente: polling de status desativado")
        return
    await asyncio.sleep(3)
    while True:
        try:
            await get_meeting_service(app.mongodb).poll_active()
        except Exception:  # noqa: BLE001
            logger.exception("Erro no polling de status")
        await asyncio.sleep(max(3, settings.RECALL_POLL_SECONDS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando %s (%s) — BASE_URL=%s", settings.APP_NAME, settings.APP_ENV, settings.BASE_URL)
    app.mongodb_client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    app.mongodb = app.mongodb_client[settings.MONGODB_DB_NAME]
    try:
        await app.mongodb.command("ping")
        await ensure_indexes(app.mongodb)
        logger.info("MongoDB conectado (%s)", settings.MONGODB_DB_NAME)
    except Exception as exc:  # noqa: BLE001
        logger.error("MongoDB indisponível: %s", exc)
        raise
    poller = asyncio.create_task(_status_poller(app))
    yield
    poller.cancel()
    app.mongodb_client.close()
    logger.info("Encerrado")


app = FastAPI(
    title=settings.APP_NAME,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routes.api import router as api_router  # noqa: E402
from app.routes.views import router as views_router  # noqa: E402

app.include_router(views_router)
app.include_router(api_router, prefix="/api")
