# Sigma CSV Data Model Migrator

Command-line tool for recreating a CSV-backed Sigma data model in another Sigma organization without uploading the CSV again.

Sigma stores an uploaded CSV as a hidden table in the connection's Databricks write-back schema. The tool discovers that physical table from the source element's generated SQL, then creates a destination data-model spec that queries the same table through the destination organization's Databricks connection.

## Requirements

- Python 3.10 or newer; no third-party packages
- Sigma API credentials for the source and destination organizations
- A Databricks connection in each organization pointing to the same workspace
- The destination connection principal must have `SELECT` access to the source write-back schema
- Keep the source data model in place so the uploaded table remains available

## Credentials

Create separate plain-text files outside the repository:

```dotenv
SIGMA_BASE_URL=https://<region>-api.sigmacomputing.com
SIGMA_CLIENT_ID=<client-id>
SIGMA_CLIENT_SECRET=<client-secret>
```

Do not use an RTF document. Keep credential files mode `0600` and never commit them.

## Inspect the source

```bash
python3 scripts/migrate_csv_data_model.py inspect \
  --source-env /secure/source.env \
  --model 'https://app.sigmacomputing.com/<org>/data-model/<model-slug>' \
  --export-spec /secure/source-model.json
```

Inspection is read-only. It returns each CSV element ID, source columns, and discovered physical Databricks relation.

## Map destination connections

Create a mapping file using the element IDs from inspection:

```json
{
  "csvSources": [
    {
      "sourceElementId": "<source-element-id>",
      "targetConnectionId": "<destination-connection-id>"
    }
  ]
}
```

Every CSV element requires one mapping. By default, the tool verifies that source and destination Databricks connections use the same host.

## Generate a migration plan

```bash
python3 scripts/migrate_csv_data_model.py plan \
  --source-env /secure/source.env \
  --target-env /secure/target.env \
  --model '<source-model-id-or-url>' \
  --mapping /secure/source-map.json \
  --target-folder '<destination-folder-id>' \
  --target-name 'Migrated model name' \
  --output /secure/create-spec.json
```

Planning is read-only against both Sigma organizations. Review the generated spec before applying it.

## Create the destination model

Add both mutation gates to the reviewed planning command:

```bash
python3 scripts/migrate_csv_data_model.py plan \
  --source-env /secure/source.env \
  --target-env /secure/target.env \
  --model '<source-model-id-or-url>' \
  --mapping /secure/source-map.json \
  --target-folder '<destination-folder-id>' \
  --output /secure/create-spec.json \
  --readback /secure/created-model.json \
  --apply --yes
```

The tool creates the model, reads it back, and fails if the destination still contains a CSV source.

## How discovery works

For every CSV element, the tool calls:

```text
GET /v2/dataModels/{dataModelId}/elements/{elementId}/query
```

Sigma's generated SQL reveals the hidden Databricks table. The tool removes Sigma's preview `LIMIT` and request comment, changes the source from `csv-table` to `sql`, rewrites source-column IDs and formulas, and preserves exact dependent column references.

## Tests

```bash
python3 -m unittest test/test_migrate_csv_data_model.py
```
