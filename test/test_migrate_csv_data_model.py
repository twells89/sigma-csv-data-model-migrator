#!/usr/bin/env python3

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "migrate_csv_data_model.py"
)
SPEC = importlib.util.spec_from_file_location("migrate_csv_data_model", SCRIPT)
MIGRATE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MIGRATE
SPEC.loader.exec_module(MIGRATE)


def source_spec():
    csv_inode = "11111111-2222-3333-4444-555555555555"
    return {
        "dataModelId": "source-model-id",
        "name": "Regional Sales",
        "folderId": "source-folder-id",
        "ownerId": "source-owner-id",
        "documentVersion": 7,
        "schemaVersion": 1,
        "kind": "data-model",
        "pages": [
            {
                "id": "page-a",
                "name": "Main",
                "elements": [
                    {
                        "id": "csv-sales",
                        "kind": "table",
                        "source": {
                            "kind": "csv-table",
                            "connectionId": "source-connection",
                            "inodeId": csv_inode,
                        },
                        "columns": [
                            {
                                "id": f"{csv_inode}/order_id",
                                "formula": "[regional_sales.csv/order_id]",
                            },
                            {
                                "id": f"{csv_inode}/net_revenue",
                                "formula": "[regional_sales.csv/net_revenue]",
                            },
                            {
                                "id": "calculated-margin",
                                "name": "Revenue Copy",
                                "formula": "[Net Revenue]",
                            },
                        ],
                        "order": [
                            f"{csv_inode}/order_id",
                            f"{csv_inode}/net_revenue",
                            "calculated-margin",
                        ],
                    },
                    {
                        "id": "control-a",
                        "kind": "control",
                        "control": {
                            "type": "date",
                            "dateColumnId": f"{csv_inode}/order_id",
                        },
                    },
                ],
            }
        ],
    }


def resolved_source():
    return MIGRATE.ResolvedSource(
        source_element_id="csv-sales",
        source_connection_id="source-connection",
        target_connection_id="target-connection",
        physical_relation="analytics.writeback.sigma_df_csv_example",
        statement=(
            "select order_id, net_revenue "
            "from analytics.writeback.sigma_df_csv_example Q1"
        ),
    )


def input_table_entry(element_id="input-1"):
    return {
        "elementId": element_id,
        "name": "Accounts",
        "type": "input-table",
        "columns": ["Account ID", "Account CSM"],
    }


class MigrationTransformTest(unittest.TestCase):
    def test_inspect_reports_csv_source_and_columns(self):
        report = MIGRATE.inspect_report(
            source_spec(),
            {
                "csv-sales": {
                    "statement": resolved_source().statement,
                    "physicalRelation": resolved_source().physical_relation,
                }
            },
        )

        self.assertEqual(report["csvSourceCount"], 1)
        source = report["csvSources"][0]
        self.assertEqual(source["sourceElementId"], "csv-sales")
        self.assertEqual(source["csvName"], "regional_sales.csv")
        self.assertEqual(source["columns"], ["order_id", "net_revenue"])
        self.assertEqual(
            source["physicalRelation"],
            "analytics.writeback.sigma_df_csv_example",
        )

    def test_plan_repoints_source_and_all_exact_id_references(self):
        planned, report = MIGRATE.plan_spec(
            source_spec(),
            [resolved_source()],
            target_folder_id="target-folder",
            target_name="Regional Sales Migrated",
        )

        self.assertEqual(
            set(planned),
            {"name", "folderId", "schemaVersion", "pages"},
        )
        self.assertEqual(planned["folderId"], "target-folder")
        self.assertEqual(planned["name"], "Regional Sales Migrated")
        table = planned["pages"][0]["elements"][0]
        self.assertEqual(
            table["source"],
            {
                "kind": "sql",
                "connectionId": "target-connection",
                "statement": (
                    "select order_id, net_revenue "
                    "from analytics.writeback.sigma_df_csv_example Q1"
                ),
            },
        )
        self.assertEqual(
            table["columns"][0],
            {
                "id": "sql-csv-sales-1",
                "formula": "[Custom SQL/order_id]",
            },
        )
        self.assertEqual(
            table["columns"][1],
            {
                "id": "sql-csv-sales-2",
                "formula": "[Custom SQL/net_revenue]",
            },
        )
        self.assertEqual(
            table["columns"][2],
            {
                "id": "calculated-margin",
                "name": "Revenue Copy",
                "formula": "[Net Revenue]",
            },
        )
        self.assertEqual(
            table["order"],
            [
                "sql-csv-sales-1",
                "sql-csv-sales-2",
                "calculated-margin",
            ],
        )
        control = planned["pages"][0]["elements"][1]
        self.assertEqual(
            control["control"]["dateColumnId"], "sql-csv-sales-1"
        )
        self.assertTrue(report["readyToCreate"])
        self.assertEqual(report["sources"][0]["migratedColumnCount"], 2)
        self.assertEqual(
            report["sources"][0]["physicalRelation"],
            "analytics.writeback.sigma_df_csv_example",
        )

    def test_generated_sql_is_sanitized_and_relation_is_extracted(self):
        generated = (
            "select order_id, net_revenue "
            "from analytics.writeback.sigma_df_csv_example Q1 limit 1000\n\n"
            '-- Sigma Σ {"request-id":"request-id","email":"user@example.com"}'
        )

        statement = MIGRATE.sanitize_generated_sql(generated)

        self.assertEqual(
            statement,
            "select order_id, net_revenue "
            "from analytics.writeback.sigma_df_csv_example Q1",
        )
        self.assertEqual(
            MIGRATE.physical_relation_from_sql(statement),
            "analytics.writeback.sigma_df_csv_example",
        )

    def test_generated_sql_rejects_multiple_statements(self):
        with self.assertRaisesRegex(MIGRATE.MigrationError, "multiple statements"):
            MIGRATE.sanitize_generated_sql(
                "select * from catalog.schema.table; drop table other"
            )

    def test_plan_requires_one_mapping_per_csv_element(self):
        with self.assertRaisesRegex(
            MIGRATE.MigrationError, "unmapped CSV elements: csv-sales"
        ):
            MIGRATE.plan_spec(
                source_spec(), [], target_folder_id="target-folder"
            )

    def test_resolve_sources_discovers_query_and_checks_databricks_host(self):
        class FakeClient:
            def __init__(self, responses):
                self.responses = responses

            def get_element_query(self, data_model_id, element_id):
                return self.responses[("query", data_model_id, element_id)]

            def get_connection(self, connection_id):
                return self.responses[("connection", connection_id)]

        source = FakeClient(
            {
                ("query", "source-model-id", "csv-sales"): {
                    "sql": (
                        "select order_id, net_revenue "
                        "from analytics.writeback.sigma_df_csv_example Q1 "
                        "limit 1000"
                    )
                },
                ("connection", "source-connection"): {
                    "type": "databricks",
                    "host": "workspace.cloud.databricks.com",
                },
            }
        )
        target = FakeClient(
            {
                ("connection", "target-connection"): {
                    "type": "databricks",
                    "host": "workspace.cloud.databricks.com",
                }
            }
        )

        resolved = MIGRATE.resolve_sources(
            source,
            target,
            source_spec(),
            [
                {
                    "sourceElementId": "csv-sales",
                    "targetConnectionId": "target-connection",
                }
            ],
        )

        self.assertEqual(resolved, [resolved_source()])

    def test_model_url_extracts_public_id(self):
        result = MIGRATE.parse_model_ref(
            "https://app.sigmacomputing.com/example/data-model/"
            "Regional-Sales-AbCdEf1234567890GhIjKl/edit"
        )
        self.assertEqual(result, "AbCdEf1234567890GhIjKl")

    def test_sigma_cli_profile_is_used_for_api_calls(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"dataModelId":"model-id"}',
                stderr="",
            )

        client = MIGRATE.SigmaCliClient("source-org", runner=runner)
        result = client.get_data_model_spec("model-id")

        self.assertEqual(result, {"dataModelId": "model-id"})
        self.assertEqual(
            calls[0][0],
            [
                "sigma",
                "api",
                "data-models",
                "spec",
                "get",
                "-f",
                "json",
                "-p",
                "source-org",
                "--params",
                '{"dataModelId":"model-id"}',
            ],
        )
        self.assertEqual(
            calls[0][1],
            {"capture_output": True, "text": True, "check": False},
        )

    def test_element_query_falls_back_to_workbook_operation(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "data-models" in command:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="no command at path",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"elementId":"element-1","sql":"select 1"}',
                stderr="",
            )

        client = MIGRATE.SigmaCliClient("source-org", runner=runner)
        result = client.get_element_query("model-id", "element-1")

        self.assertEqual(result["elementId"], "element-1")
        self.assertIn("data-models", calls[0])
        self.assertIn("workbooks", calls[1])

    def test_data_model_elements_are_paginated(self):
        calls = []

        def runner(command, **_kwargs):
            params = json.loads(command[command.index("--params") + 1])
            calls.append(params)
            if "page" not in params:
                payload = {
                    "entries": [{"elementId": "first"}],
                    "nextPage": "cursor-2",
                }
            else:
                payload = {
                    "entries": [{"elementId": "second"}],
                    "nextPage": None,
                }
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )

        client = MIGRATE.SigmaCliClient("source-org", runner=runner)
        result = client.list_data_model_elements("model-id")

        self.assertEqual(
            [entry["elementId"] for entry in result["entries"]],
            ["first", "second"],
        )
        self.assertEqual(calls[0], {"dataModelId": "model-id", "limit": 500})
        self.assertEqual(
            calls[1],
            {"dataModelId": "model-id", "limit": 500, "page": "cursor-2"},
        )

    def test_input_table_only_model_is_synthesized(self):
        class Client:
            def get_data_model_spec(self, _model_id):
                return {
                    "dataModelId": "model-id",
                    "schemaVersion": 1,
                    "pages": [],
                }

            def list_data_model_elements(self, _model_id):
                return {"entries": [input_table_entry()]}

        spec = MIGRATE.get_spec(Client(), "model-id")
        element = MIGRATE.csv_elements(spec)[0]

        self.assertEqual(spec["pages"][0]["name"], "Input Tables")
        self.assertEqual(element["source"]["inodeId"], "input-1")
        self.assertEqual(
            [column["id"] for column in element["columns"]],
            ["input-1/Account_ID", "input-1/Account_CSM"],
        )

    def test_mixed_legacy_csv_and_input_table_are_both_synthesized(self):
        source = source_spec()

        class Client:
            def get_data_model_spec(self, _model_id):
                return source

            def list_data_model_elements(self, _model_id):
                return {"entries": [input_table_entry()]}

        spec = MIGRATE.get_spec(Client(), "model-id")

        self.assertEqual(
            {element["id"] for element in MIGRATE.csv_elements(spec)},
            {"csv-sales", "input-1"},
        )

    def test_input_table_still_validates_target_connection_type(self):
        synthetic = {
            "dataModelId": "model-id",
            "pages": [
                {
                    "id": "page-1",
                    "name": "Page 1",
                    "elements": [
                        {
                            "id": "input-1",
                            "kind": "table",
                            "source": {
                                "kind": "csv-table",
                                "connectionId": None,
                                "inodeId": "input-1",
                            },
                            "columns": [
                                {
                                    "id": "input-1/Account_ID",
                                    "formula": "[Accounts/Account ID]",
                                }
                            ],
                            "order": ["input-1/Account_ID"],
                        }
                    ],
                }
            ],
        }

        class SourceClient:
            def get_element_query(self, _model_id, _element_id):
                return {
                    "sql": (
                        "select Account_ID "
                        "from catalog.writeback.sigma_input_table Q1 limit 1000"
                    )
                }

        class TargetClient:
            def get_connection(self, _connection_id):
                return {"type": "snowflake", "host": "not-databricks"}

        with self.assertRaisesRegex(MIGRATE.MigrationError, "not Databricks"):
            MIGRATE.resolve_sources(
                SourceClient(),
                TargetClient(),
                synthetic,
                [
                    {
                        "sourceElementId": "input-1",
                        "targetConnectionId": "target-connection",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
