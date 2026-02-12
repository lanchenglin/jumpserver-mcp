from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
    )
    server_port: int = 8099
    api_key: str = ''
    api_base_url:str = ''
    api_token:str=  ''
    access_key_id: str = ''
    access_key_secret: str = ''
    jms_org_id: str = ''
    # JumpServer SSH 网关配置（用于通过会话通道执行命令）
    ssh_gateway_host: str = ''
    ssh_gateway_port: int = 2222
    ssh_gateway_username: str = ''
    ssh_gateway_password: str = ''
    default_system_user: str = 'root'
    base_path: str = '/sse'
    swagger_url: str = ''
    log_level: str = 'INFO'
    debug: bool = False
    jumpserver_url: str = ''


settings = Settings()
