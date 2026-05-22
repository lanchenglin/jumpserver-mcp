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
    # SSH 网关配置
    ssh_gateway_host: str = ''
    ssh_gateway_port: int = 2222
    ssh_gateway_username: str = ''
    ssh_gateway_password: str = ''
    ssh_gateway_private_key_path: str = ''
    ssh_gateway_known_hosts_path: str = ''
    default_system_user: str = 'root'
    ssh_connect_timeout: int = 30
    ssh_command_timeout: int = 30
    ssh_pool_max_connections: int = 10
    ssh_pool_idle_timeout: int = 1500
    ssh_health_check_interval: int = 60
    ssh_command_policy_mode: str = 'none'
    ssh_command_policy_patterns: str = ''
    max_command_output_bytes: int = 1_048_576
    max_sftp_upload_bytes: int = 10_485_760
    max_sftp_download_bytes: int = 10_485_760
    max_sftp_list_entries: int = 1000
    mcp_worker_threads: int = 8


settings = Settings()
