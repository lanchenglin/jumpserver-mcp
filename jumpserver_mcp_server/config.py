from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        extra='ignore',
    )
    server_port: int = 8099
    api_key: str = ''
    api_base_url: str = ''
    api_token: str = ''
    access_key_id: str = ''
    access_key_secret: str = ''
    jms_org_id: str = ''
    base_path: str = '/sse'
    swagger_url: str = ''
    log_level: str = 'INFO'
    debug: bool = False
    jumpserver_url: str = 'http://jumpserver.ks.gillion.com.cn'


settings = Settings()
