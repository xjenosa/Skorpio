from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Database
    database_url: str = "postgresql+asyncpg://skorpio:skorpio@localhost:5432/skorpio"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Paths
    cache_dir: Path = Path("./data/cache")
    results_dir: Path = Path("./data/results")
    plans_dir: Path = Path("./data/plans")            # rendered siting-plan artifacts (PDF, GeoJSON)
    transmission_dir: Path = Path("./data/transmission")  # transmission/topology files served back to the viewer

    # External APIs — energy / grid data
    eia_api_key: str = ""
    eia_base_url: str = "https://api.eia.gov/v2"

    # NREL — renewable resource / cost data
    nrel_api_key: str = ""
    nrel_base_url: str = "https://developer.nrel.gov/api"

    # OpenEI — utility rates and capacity data
    openei_api_key: str = ""
    openei_base_url: str = "https://api.openei.org"

    # ISO bulletins (LMP, generation mix, transmission constraints)
    pjm_base_url: str = "https://api.pjm.com/api/v1"
    pjm_api_key: str = ""
    ercot_base_url: str = "https://api.ercot.com/api/public-reports"
    ercot_api_key: str = ""
    caiso_oasis_base_url: str = "https://oasis.caiso.com/oasisapi"
    miso_base_url: str = "https://api.misoenergy.org"
    spp_base_url: str = "https://marketplace.spp.org/web/file-browser-api"

    # Open-Meteo — site weather forecasts (free, no key required)
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"

    # NRCan Wildland Fire (live perimeters + Fire Weather Index, no key)
    nrcan_wildfire_base_url: str = "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs"

    # PeeringDB — internet exchange directory (public read, no key)
    peeringdb_base_url: str = "https://www.peeringdb.com/api"

    # ECCC — Canadian hydrometric + climate normals (no key)
    eccc_base_url: str = "https://api.weather.gc.ca"

    # Climate Atlas of Canada — future projections (no key)
    climate_atlas_base_url: str = "https://climateatlas.ca/data/api/v2"

    # arXiv — energy / grid policy preprints (no key required)
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_max_results: int = 5

    # ArcGIS / Esri — OAuth 2.0 app-authentication credentials minted in an
    # ArcGIS Online org (Content → New item → Developer credentials →
    # OAuth 2.0 app auth → privileges: Basemaps, Geocoding, Data enrichment,
    # Premium content). Backend mints short-lived access tokens via the
    # client_credentials grant and attaches them to GeoEnrichment /
    # Geocoding calls. Both blank = integration disabled, all callers fall
    # back to their existing synthesized / StatsCan-registry path.
    arcgis_client_id: str = ""
    arcgis_client_secret: str = ""
    arcgis_oauth_token_url: str = "https://www.arcgis.com/sharing/rest/oauth2/token"
    arcgis_geoenrichment_url: str = (
        "https://geoenrich.arcgis.com/arcgis/rest/services/World/"
        "geoenrichmentserver/Geoenrichment/enrich"
    )
    arcgis_geocoding_url: str = (
        "https://geocode-api.arcgis.com/arcgis/rest/services/"
        "World/GeocodeServer/findAddressCandidates"
    )

    # Placement scoring
    scoring_horizon_months: int = 18      # how far forward LMP/carbon forecasts are evaluated
    scoring_pareto_front_k: int = 12      # default top-K front size
    scoring_timeout_seconds: int = 120

    # Pipeline
    max_regions: int = 5
    min_site_candidates: int = 24

    # MCP — optional tool interface layer (does not affect FastAPI)
    enable_mcp: bool = False

    # Snowflake (optional — Site Intelligence Layer)
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_warehouse: str = ""
    snowflake_database: str = ""
    snowflake_schema: str = ""

    # ── Stage 2: auth ─────────────────────────────────────────────────── #
    # Google OAuth — credentials come from console.cloud.google.com.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Resend — used to send the 6-digit email login codes.
    resend_api_key: str = ""
    resend_from_email: str = "onboarding@resend.dev"

    # JWT signing. SKORPIO_AUTH_SECRET MUST be set in production; the dev
    # fallback below is only suitable for local prototyping. Sessions live for
    # SKORPIO_AUTH_TOKEN_TTL_HOURS once issued.
    skorpio_auth_secret: str = "dev-only-change-me-in-env"
    skorpio_auth_token_ttl_hours: int = 168  # 7 days

    # Comma-separated allowlist of email addresses permitted to sign in. Empty
    # = no restriction (dev default — anyone with the URL can log in). Set
    # this to lock the deployed instance down so only your own Claude API
    # spend is exposed. Matches case-insensitively, both auth paths
    # (email magic-code AND Google OAuth) are enforced.
    skorpio_allowed_emails: str = ""

    # Where to redirect users back to after Google OAuth completes.
    frontend_url: str = "http://localhost:3000"

    # ── Canadian grid data sources (open, no API key required) ────────── #
    # Public reports for the Ontario (IESO), Alberta (AESO), and Québec
    # (Hydro-Québec) grid operators. URLs are documented here so the
    # canada_grid client knows where to look; if the live fetch fails the
    # client falls back to provincial reference constants instead.
    ieso_realtime_totals_url: str = (
        "https://reports-public.ieso.ca/public/RealtimeMktTotals/"
        "PUB_RealtimeMktTotals.csv"
    )
    aeso_csd_url: str = "https://www.aeso.ca/assets/Current-Supply-Demand-Report.csv"
    hydroquebec_demand_url: str = "https://www.hydroquebec.com/data/donnees-ouvertes/json/demande.json"

    # Default Canadian provinces considered when no specific region is given.
    # ISO 3166-2 codes prefixed with "CA-" so they round-trip to the
    # carbon-intensity zone keys (CA-ON, CA-QC, CA-AB, etc.).
    default_canadian_provinces: list[str] = [
        "CA-ON", "CA-QC", "CA-AB", "CA-BC", "CA-MB",
    ]

    def ensure_dirs(self) -> None:
        for d in (self.cache_dir, self.results_dir, self.plans_dir, self.transmission_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
