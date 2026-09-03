from decimal import Decimal
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PROOFCLOSE_", extra="ignore")

    environment: str = Field(default="demo", alias="PROOFCLOSE_ENV")
    data_dir: Path = Field(default=Path(".runtime"), alias="PROOFCLOSE_DATA_DIR")
    demo_tenant_id: str = Field(default="demo_merchant", alias="PROOFCLOSE_DEMO_TENANT_ID")
    demo_actor_id: str = Field(default="demo_operator", alias="PROOFCLOSE_DEMO_ACTOR_ID")
    bank_pending_hours: int = Field(default=3, alias="PROOFCLOSE_BANK_PENDING_HOURS", ge=1, le=168)
    nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(default="https://integrate.api.nvidia.com/v1", alias="NVIDIA_BASE_URL")
    nvidia_model: str = Field(default="nvidia/llama-3.3-nemotron-super-49b-v1", alias="NVIDIA_MODEL")
    llm_timeout_seconds: int = Field(default=15, alias="LLM_TIMEOUT_SECONDS", ge=1, le=120)
    llm_max_retries: int = Field(default=1, alias="LLM_MAX_RETRIES", ge=0, le=3)
    provider_call_budget: int = Field(default=2, alias="PROOFCLOSE_PROVIDER_CALL_BUDGET", ge=0, le=100)
    pricing_version: str | None = Field(default=None, alias="PROOFCLOSE_PRICING_VERSION")
    pricing_input_per_1k: Decimal | None = Field(default=None, alias="PROOFCLOSE_PRICING_INPUT_PER_1K")
    pricing_output_per_1k: Decimal | None = Field(default=None, alias="PROOFCLOSE_PRICING_OUTPUT_PER_1K")
    allow_destructive_demo_reset: bool = Field(
        default=False, alias="PROOFCLOSE_ALLOW_DESTRUCTIVE_DEMO_RESET"
    )

    @property
    def demo_mode(self) -> bool:
        return self.environment.lower() == "demo"

    @property
    def product_database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'proofclose.db').as_posix()}"

    @property
    def observability_database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'observability.db').as_posix()}"
