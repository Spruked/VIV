# VIV CRM

Windows-native Vector Intelligence Vault CRM. Start with `start_cali_crm.bat`.

Runtime services: VIV API `21000`, VIV frontend `21010`, and local communications API `19000`.

## Intelligence operations

- **Discover Connections** uses the bounded local `/cali/intelligence/scan` engine.
- **Expand Dossier** produces deterministic, public-record reference paths without asserting findings.
- **Contact Research** records public-source results as `unverified_public_source` evidence.
- The local daily sweep is registered as `VIV Daily Dossier Sweep` at 02:10.

Provider configuration is documented in `config/research_providers.example.json`; never store API keys in the repository.
