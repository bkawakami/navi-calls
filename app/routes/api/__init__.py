from fastapi import APIRouter

from .assistant import router as assistant_router
from .meetings import router as meetings_router
from .webhooks import router as webhooks_router

router = APIRouter()
router.include_router(meetings_router, prefix="/meetings", tags=["meetings"])
router.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
router.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
