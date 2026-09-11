# VIV System Boundary

## Status

VIV is a new authoritative system and repository. It succeeds the former CRM but does not inherit the old CRM repository as-is.

Legacy source such as `Spruked/CRM_Master_Copy` may be reviewed and selectively migrated, but old files, assumptions, ports, names, credentials, databases, runtime logs, and obsolete integrations must not be copied forward without validation.

## Current runtime identity

- Product/system name: VIV CRM
- Expansion: Vector Intelligence Vault CRM
- Windows launcher: `start_cali_crm.bat`
- VIV API: `21000`
- VIV frontend: `21010`
- Local communications API: `19000`

## Intelligence operations

### Discover Connections
Uses the bounded local endpoint:

`/cali/intelligence/scan`

### Expand Dossier
Produces deterministic public-record reference paths. It must not assert that a referenced public-record result is a verified fact merely because the path was generated.

### Contact Research
Public-source findings are recorded as evidence with the status:

`unverified_public_source`

### Daily sweep
Registered local task:

`VIV Daily Dossier Sweep`

Scheduled time:

`02:10`

## Provider configuration

Provider templates belong in:

`config/research_providers.example.json`

Live API keys and provider credentials must never be committed.

## Authority model

VIV is the CRM/contact-intelligence and relationship-context authority. The communications service on port `19000` is a cooperating local service and should not be treated as the owner of VIV contact intelligence.

Future integrations, including Pro Prime Financial Systems, should consume VIV relationship and contact context through explicit interfaces rather than duplicating VIV's contact database or intelligence records.

## Migration rule

The new repository should receive the current VIV source from the live Windows-native implementation. Before migration:

1. inventory the live VIV working tree;
2. exclude secrets, databases, logs, cached research, generated dossiers, and personal runtime data;
3. compare candidate legacy CRM files against the live VIV implementation;
4. migrate only files that are part of the current VIV system;
5. preserve VIV naming and current ports;
6. validate `start_cali_crm.bat`, API `21000`, frontend `21010`, communications API `19000`, intelligence scan, dossier expansion, contact research, and the daily dossier sweep;
7. commit the clean VIV baseline as the first complete source baseline in this repository.
