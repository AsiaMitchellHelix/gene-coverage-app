from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 8

    saml_sp_entity_id: str
    saml_sp_acs_url: str
    saml_idp_metadata_url: str

    aws_region: str = "us-east-1"
    ses_sender: str

    hcluster_host: str
    hcluster_user: str
    hcluster_ssh_key_path: str
    hcluster_scratch_dir: str
    hcluster_cram_list: str

    gtf_path: str
    dbsnp_vcf_path: str

    min_depth: int = 20

    class Config:
        env_file = ".env"


settings = Settings()
