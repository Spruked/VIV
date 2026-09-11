# VIV CRM

Windows-native Vector Intelligence Vault CRM. Start with `start_cali_crm.bat`.

Runtime services: VIV API `21000`, VIV frontend `21010`, and local communications API `19000`.

## Intelligence operations

- **Discover Connections** uses the bounded local `/cali/intelligence/scan` engine.
- **Expand Dossier** produces deterministic, public-record reference paths without asserting findings.
- **Contact Research** records public-source results as `unverified_public_source` evidence.
- The local daily sweep is registered as `VIV Daily Dossier Sweep` at 02:10.

Provider configuration is documented in `config/research_providers.example.json`; never store API keys in the repository.

## Repository authority

`Spruked/VIV` is the authoritative repository for VIV as a new system.

VIV is the successor to the former CRM, but this repository is not a historical mirror of `CRM_Master_Copy`. Legacy CRM code is reference material only and must be reviewed before it is carried forward.

The current VIV system combines CRM/contact intelligence with the local communications layer while preserving clear authority boundaries between contact intelligence, communications transport, and external systems.

## Runtime boundary

- VIV API: `21000`
- VIV frontend: `21010`
- Local communications API: `19000`

Secrets, runtime databases, customer/contact data, research results containing personal data, API keys, tokens, logs, and generated evidence stores must not be committed to this repository.
