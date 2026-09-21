# Sigma CSV Data Model Migrator

Command-line tool for recreating a CSV-backed Sigma data model in another Sigma organization without uploading the CSV again.

Sigma stores an uploaded CSV as a hidden table in the connection's Databricks write-back schema. The tool discovers that physical table from the source element's generated SQL, then creates a destination data-model spec that queries the same table through the destination organization's Databricks connection.

## Requirements

- Python 3.10 or newer; no third-party Python packages
- [Sigma CLI](https://help.sigmacomputing.com/docs/install-and-configure-the-sigma-cli)
- An OAuth Sigma CLI profile for each organization
- A Databricks connection in each organization pointing to the same workspace
- The destination connection principal must have `SELECT` access to the source write-back schema
- Keep the source data model in place so the uploaded table remains available

## Authenticate with OAuth

Create one Sigma CLI profile for each organization. The CLI handles browser login, secure token storage, and refresh; this tool does not read credentials or tokens.

```bash
sigma auth login
# Create OAuth profile: source-org

sigma auth login
# Create OAuth profile: target-org

sigma -p source-org auth status
sigma -p target-org auth status
```

## Inspect the source

```bash
python3 scripts/migrate_csv_data_model.py inspect \
  --source-profile source-org \
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
  --source-profile source-org \
  --target-profile target-org \
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
  --source-profile source-org \
  --target-profile target-org \
  --model '<source-model-id-or-url>' \
  --mapping /secure/source-map.json \
  --target-folder '<destination-folder-id>' \
  --output /secure/create-spec.json \
  --readback /secure/created-model.json \
  --apply --yes
```

The tool creates the model, reads it back, and fails if the destination still contains a CSV source.

## How discovery works

For every CSV element, the tool runs the Sigma CLI equivalent of:

```text
GET /v2/dataModels/{dataModelId}/elements/{elementId}/query
```

Sigma's generated SQL reveals the hidden Databricks table. The tool removes Sigma's preview `LIMIT` and request comment, changes the source from `csv-table` to `sql`, rewrites source-column IDs and formulas, and preserves exact dependent column references.

## Tests

```bash
python3 -m unittest test/test_migrate_csv_data_model.py
```
