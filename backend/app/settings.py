from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"
    # Use "openai" for any OpenAI-compatible chat-completions API (e.g. Groq).
    llm_provider: str = "off"  # openai | ollama | off
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "llama-3.3-70b-versatile"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self):
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()
