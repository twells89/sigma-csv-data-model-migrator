# Sigma CSV Data Model Migrator

Command-line tool for recreating a CSV-backed Sigma data model in another Sigma organization without uploading the CSV again.

Sigma stores an uploaded CSV as a hidden table in the connection's Databricks write-back schema. The tool discovers that physical table from the source element's generated SQL, then creates a destination data-model spec that queries the same table through the destination organization's Databricks connection.

## Requirements

- Python 3.10 or newer
- `pipx`
- [Sigma CLI](https://help.sigmacomputing.com/docs/install-and-configure-the-sigma-cli)
- An OAuth Sigma CLI profile for each organization
- A Databricks connection in each organization pointing to the same workspace
- The destination connection principal must have `SELECT` access to the source write-back schema
- Keep the source data model in place so the uploaded table remains available

The migrator has no third-party Python runtime dependencies.

## Install

### 1. Install the Sigma CLI

macOS with Homebrew:

```bash
brew install sigmacomputing/tap/sigma-computing-cli
```

macOS or Linux with the official installer:

```bash
curl --proto '=https' --tlsv1.2 -LsSf \
  https://assets.sigmacomputing.com/sigma-cli/releases/latest/sigma-cli-installer.sh | sh
export PATH="$HOME/.sigma-cli/bin:$PATH"
```

Confirm installation:

```bash
sigma --version
```

### 2. Install pipx

macOS with Homebrew:

```bash
brew install pipx
pipx ensurepath
```

Or with Python:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Restart your shell after `ensurepath` if the command is not immediately available.

### 3. Install the migrator

Install directly from GitHub:

```bash
pipx install "git+https://github.com/twells89/sigma-csv-data-model-migrator.git"
```

Alternatively, install from a local checkout:

```bash
git clone https://github.com/twells89/sigma-csv-data-model-migrator.git
cd sigma-csv-data-model-migrator
pipx install .
```

Confirm installation:

```bash
sigma-csv-dm-migrate --help
```

Upgrade or uninstall:

```bash
pipx upgrade sigma-csv-data-model-migrator
pipx uninstall sigma-csv-data-model-migrator
```

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
sigma-csv-dm-migrate inspect \
  --source-profile source-org \
  --model 'https://app.sigmacomputing.com/<org>/data-model/<model-slug>' \
  --export-spec ./source-model.json
```

Inspection is read-only. It returns each CSV element ID, source columns, and discovered physical Databricks relation.

## Map destination connections

Create `source-map.json` using the element IDs from inspection:

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
sigma-csv-dm-migrate plan \
  --source-profile source-org \
  --target-profile target-org \
  --model '<source-model-id-or-url>' \
  --mapping ./source-map.json \
  --target-folder '<destination-folder-id>' \
  --target-name 'Migrated model name' \
  --output ./create-spec.json
```

Planning is read-only against both Sigma organizations. Review `create-spec.json` before applying it.

## Create the destination model

Add both mutation gates to the reviewed planning command:

```bash
sigma-csv-dm-migrate plan \
  --source-profile source-org \
  --target-profile target-org \
  --model '<source-model-id-or-url>' \
  --mapping ./source-map.json \
  --target-folder '<destination-folder-id>' \
  --output ./create-spec.json \
  --readback ./created-model.json \
  --apply --yes
```

The tool creates the model, reads it back, and fails if the destination still contains a CSV source.

## How discovery works

The tool supports both legacy `csv-table` elements and current CSV-backed input-table elements. For every discovered source, it first uses the data-model query operation and falls back to the equivalent workbook operation for older CLI/OpenAPI versions:

```text
GET /v2/dataModels/{dataModelId}/elements/{elementId}/query
GET /v2/workbooks/{workbookId}/elements/{elementId}/query
```

Sigma's generated SQL reveals the hidden Databricks table. The tool removes Sigma's preview `LIMIT` and request comment, changes the source from `csv-table` to `sql`, rewrites source-column IDs and formulas, and preserves exact dependent column references.

## Input-table snapshot behavior

Current Sigma CSV uploads can be represented as writeback-backed input tables. Their generated SQL can include a `ROW_VERSION <= ...` boundary. Migrating that SQL creates a frozen snapshot at plan time: edits made later to the source input table do not automatically propagate to the destination data model. Generate a new plan and update the destination model when a newer snapshot is required.

## Development

Install an editable checkout and run the tests:

```bash
git clone https://github.com/twells89/sigma-csv-data-model-migrator.git
cd sigma-csv-data-model-migrator
python3 -m pip install -e .
python3 -m unittest discover -s test -p 'test_*.py'
```
