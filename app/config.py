"""Configurações da aplicação via variáveis de ambiente (Pydantic Settings)."""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Aplicação
    APP_NAME: str = "Navi"
    APP_ENV: str = "development"  # development | production
    DEBUG: bool = True
    SECRET_KEY: str = "troque-esta-chave"  # usada para assinar tokens da página da assistente

    # Servidor
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # URL pública (ngrok/cloudflared/Cloud Run). Precisa ser alcançável pela Recall.ai.
    BASE_URL: str = "http://localhost:8000"

    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27027"
    MONGODB_DB_NAME: str = "navi"

    # Painel (opcional): se definido, exige HTTP Basic no painel e nas APIs do painel
    DASHBOARD_PASSWORD: Optional[str] = None
    DASHBOARD_USER: str = "navi"

    # Recall.ai
    RECALL_API_KEY: Optional[str] = None
    RECALL_REGION: str = "us-west-2"  # us-west-2 (pay-as-you-go) | us-east-1 | eu-central-1 | ap-northeast-1
    # Segredo de verificação (whsec_...): "Workspace Secret" (contas novas, cabeçalhos webhook-*) ou segredo Svix do endpoint (contas antigas, svix-*)
    RECALL_WEBHOOK_SECRET: Optional[str] = None
    RECALL_REALTIME_SECRET: Optional[str] = None  # segredo embutido na URL dos webhooks em tempo real (?secret=)
    RECALL_BOT_NAME: str = "Navi | Assistente IA"
    RECALL_BOT_VARIANT: str = "web_4_core"  # web | web_4_core (recomendado p/ Output Media) | web_gpu
    # recallai_streaming (sem chave extra; em pt só no modo de precisão, atrasado 3-10 min)
    # deepgram_streaming | assembly_ai_v3_streaming | speechmatics_streaming | elevenlabs_streaming (tempo real; chave do provedor no dashboard da Recall)
    # none (sem transcrição da Recall; usa só a transcrição da OpenAI, sem nome dos falantes)
    RECALL_TRANSCRIPT_PROVIDER: str = "recallai_streaming"
    RECALL_TRANSCRIPT_LANGUAGE: str = "pt"  # pt (Recall/Speechmatics/ElevenLabs) · pt-BR (Deepgram)
    RECALL_POLL_SECONDS: int = 10  # polling de status do bot (fallback dos webhooks)

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_REALTIME_MODEL: str = "gpt-realtime-2.1"
    OPENAI_REALTIME_VOICE: str = "marin"
    OPENAI_REALTIME_REASONING: str = "low"  # minimal | low | medium (só modelos gpt-realtime-2.x)
    OPENAI_TRANSCRIBE_MODEL: str = "gpt-transcribe"
    OPENAI_TURN_DETECTION: str = "server_vad"  # server_vad | semantic_vad
    OPENAI_VAD_SILENCE_MS: int = 700
    OPENAI_TEXT_MODEL: str = "gpt-5.6-sol"
    OPENAI_TEXT_MODEL_FALLBACKS: str = "gpt-5.5,gpt-5.4-mini"  # usados se o modelo principal falhar
    OPENAI_TEXT_REASONING: str = "medium"  # none | low | medium | high
    OPENAI_EPHEMERAL_TTL_SECONDS: int = 600

    # Assistente
    NAVI_WAKE_WORDS: str = "navi,návi,naví,navy,nabi,navie,navvy"
    NAVI_MAX_ANSWER_SECONDS: int = 25
    NAVI_TRANSPORT: str = "auto"  # auto (WebRTC com fallback WebSocket) | webrtc | websocket

    @property
    def recall_base_url(self) -> str:
        return f"https://{self.RECALL_REGION}.recall.ai"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def wake_words(self) -> list[str]:
        return [w.strip().lower() for w in self.NAVI_WAKE_WORDS.split(",") if w.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
