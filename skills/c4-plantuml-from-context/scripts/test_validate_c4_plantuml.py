#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = SCRIPT_DIR / "validate_c4_plantuml.py"
SPEC = importlib.util.spec_from_file_location("validate_c4_plantuml", SCRIPT_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)

FIXTURES_DIR = SCRIPT_DIR / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"


class ValidateC4PlantUMLTests(unittest.TestCase):
    def validate_fixture(self, path: Path, **kwargs):
        return VALIDATOR.validate_file(path, plantuml_mode="off", **kwargs)

    def validate_text(self, text: str, **kwargs):
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)
        return VALIDATOR.validate_file(temp_path, plantuml_mode="off", **kwargs)

    def test_valid_smoke_fixtures_pass(self):
        fixture_names = [
            "system_context.puml",
            "system_landscape.puml",
            "container.puml",
            "component.puml",
            "dynamic.puml",
            "dynamic_relindex.puml",
            "deployment.puml",
        ]
        for name in fixture_names:
            with self.subTest(name=name):
                result = self.validate_fixture(VALID_DIR / name)
                self.assertEqual(result.errors, [])
                self.assertEqual(result.warnings, [])

    def test_missing_title_is_error(self):
        result = self.validate_fixture(INVALID_DIR / "missing_title.puml")
        self.assertTrue(any("missing a title" in error for error in result.errors))

    def test_missing_legend_is_error(self):
        result = self.validate_fixture(INVALID_DIR / "missing_legend.puml")
        self.assertTrue(any("missing a legend directive" in error for error in result.errors))

    def test_house_style_flags_can_disable_title_and_legend_requirements(self):
        title_result = self.validate_fixture(INVALID_DIR / "missing_title.puml", require_title=False)
        legend_result = self.validate_fixture(INVALID_DIR / "missing_legend.puml", require_legend=False)
        self.assertEqual(title_result.errors, [])
        self.assertEqual(legend_result.errors, [])

    def test_missing_technology_is_warning(self):
        result = self.validate_fixture(INVALID_DIR / "missing_technology.puml")
        self.assertEqual(result.errors, [])
        self.assertTrue(any("missing a technology" in warning for warning in result.warnings))

    def test_named_args_without_dollar_do_not_fill_positional_slots(self):
        result = self.validate_fixture(INVALID_DIR / "named_arg_descr_without_dollar_missing_technology.puml")
        self.assertEqual(result.errors, [])
        self.assertTrue(any("missing a technology" in warning for warning in result.warnings))

    def test_unknown_alias_is_error(self):
        result = self.validate_fixture(INVALID_DIR / "unknown_alias_relationship.puml")
        self.assertTrue(any("unknown target alias" in error for error in result.errors))

    def test_wrong_include_is_error(self):
        result = self.validate_fixture(INVALID_DIR / "wrong_include_for_component.puml")
        self.assertTrue(any("container diagram must not include component" in error for error in result.errors))

    def test_show_legend_must_be_last(self):
        result = self.validate_fixture(INVALID_DIR / "show_legend_not_last.puml")
        self.assertTrue(any("must be the last statement" in error for error in result.errors))

    def test_legend_token_inside_label_does_not_satisfy_legend_requirement(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Legend Token in Label
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Calls SHOW_LEGEND() helper")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("missing a legend directive" in error for error in result.errors))

    def test_nested_show_legend_inside_relationship_args_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Nested Legend
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", SHOW_LEGEND())
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`SHOW_LEGEND` must be a standalone top-level statement" in error for error in result.errors))
        self.assertTrue(any("missing a legend directive" in error for error in result.errors))

    def test_relindex_dynamic_helpers_are_accepted(self):
        result = self.validate_fixture(VALID_DIR / "dynamic_relindex.puml")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    def test_top_level_element_typo_gets_explicit_suggestion(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Element Typo
LAYOUT_WITH_LEGEND()
Persn(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown element `Persn`; did you mean `Person`?" in error for error in result.errors))

    def test_top_level_relationship_typo_gets_explicit_suggestion(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Relationship Typo
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rl(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown relationship `Rl`; did you mean `Rel`?" in error for error in result.errors))

    def test_directory_scan_ignores_appledouble_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            visible = root / "ok.puml"
            visible.write_text(
                "@startuml\n!include <C4/C4_Context>\ntitle System Context diagram for Visible App\nLAYOUT_WITH_LEGEND()\nSystem(app, \"App\", \"Handles requests\")\n@enduml\n",
                encoding="utf-8",
            )
            (root / "._hidden.puml").write_bytes(b"\xff\xfe\x00\x00")
            (root / ".also-hidden.puml").write_text("@startuml\n@enduml\n", encoding="utf-8")
            macosx_dir = root / "__MACOSX"
            macosx_dir.mkdir()
            (macosx_dir / "ghost.puml").write_bytes(b"\xff\xfe\x00\x00")

            paths = VALIDATOR.iter_paths([str(root)])
            self.assertEqual(paths, [visible])

    def test_directory_cli_does_not_crash_on_hidden_binary_sidecars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "ok.puml").write_text(
                "@startuml\n!include <C4/C4_Context>\ntitle System Context diagram for Visible App\nLAYOUT_WITH_LEGEND()\nSystem(app, \"App\", \"Handles requests\")\n@enduml\n",
                encoding="utf-8",
            )
            (root / "._broken.puml").write_bytes(b"\xff\xfe\x00\x00")

            exit_code = VALIDATOR.main([str(root), "--plantuml", "off"])
            self.assertEqual(exit_code, 0)

    def test_non_utf8_file_is_reported_not_crashed(self):
        with tempfile.NamedTemporaryFile(suffix=".puml", delete=False) as handle:
            temp_path = Path(handle.name)
        temp_path.write_bytes(b"\xff\xfe\x00\x00")

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unable to decode UTF-8" in error for error in result.errors))

    def test_single_quoted_boundary_label_is_parsed(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Quoted Boundary
LAYOUT_WITH_LEGEND()
System_Boundary(c1, 'Sample') {
    Container(api, "API", "Python", "Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_title_with_apostrophe_does_not_trigger_false_warning(self):
        text = """
@startuml
!include <C4/C4_Context>
title Bob's context diagram for App
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertFalse(any("does not clearly state" in warning for warning in result.warnings))

    def test_title_with_trailing_apostrophe_plural_does_not_trigger_false_warning(self):
        text = """
@startuml
!include <C4/C4_Context>
title Payments' context diagram for App
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertFalse(any("does not clearly state" in warning for warning in result.warnings))

    def test_inline_block_comment_before_statement_is_preserved(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for Inline Comment
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
/' comment '/ Rel(user, app, "Sends request", $index=1)
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_inline_block_comment_after_statement_does_not_corrupt_args(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Inline Comment
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Uses") /' comment ) '/
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertTrue(any("too generic" in warning for warning in result.warnings))

    def test_multiline_title_is_recognized(self):
        text = """
@startuml
!include <C4/C4_Context>
title
 System Context diagram for Multiline Title App
end title
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertFalse(any("missing a title" in error for error in result.errors))

    def test_missing_end_title_reports_explicit_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title
 System Context diagram for Broken Title
LAYOUT_WITH_LEGEND()
System(app, "App", "Handles requests")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("missing `end title`" in error for error in result.errors))
        self.assertFalse(any("missing a legend directive" in error for error in result.errors))

    def test_unclosed_block_comment_reports_explicit_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Broken Comment
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
/' comment starts
System(app, "App", "Handles requests")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("block comment is missing closing" in error for error in result.errors))
        self.assertFalse(any("missing a legend directive" in error for error in result.errors))

    def test_unterminated_multiline_call_reports_explicit_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Missing Paren
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request"
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unterminated macro call or unbalanced parentheses" in error for error in result.errors))

    def test_boundary_alias_cannot_be_rel_endpoint(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Boundary Endpoint
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System_Boundary(sys_boundary, "App") {
    Container(api, "API", "Python", "Handles requests")
}
Rel(user, sys_boundary, "Uses app", "HTTPS")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("boundary alias `sys_boundary`" in error for error in result.errors))

    def test_deployment_node_cannot_be_rel_endpoint(self):
        text = """
@startuml
!include <C4/C4_Deployment>
title Deployment diagram for Node Endpoint
LAYOUT_WITH_LEGEND()
Deployment_Node(cloud, "AWS", "Cloud") {
    Container(api, "API", "Go", "Handles requests")
}
Rel(api, cloud, "Runs on")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("deployment-node alias `cloud`" in error for error in result.errors))

    def test_relindex_is_rejected_outside_dynamic(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid RelIndex
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
RelIndex(1, user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("dynamic-only relationship macro `RelIndex`" in error for error in result.errors))

    def test_index_named_arg_is_rejected_outside_dynamic(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid Index
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request", $index=1)
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("named argument `index`" in error for error in result.errors))

    def test_sequence_rel_keyword_is_rejected_in_dynamic(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for Invalid Sequence Surface
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request", $index=1, $rel="->")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("named argument `rel`" in error for error in result.errors))
        self.assertTrue(any("C4_Sequence.puml" in error for error in result.errors))

    def test_unknown_relationship_macro_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid Rel Macro
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel_Sideways(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown relationship macro `Rel_Sideways`" in error for error in result.errors))

    def test_unknown_relationship_named_arg_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid Named Arg
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request", tech="HTTPS")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unsupported named argument(s): `tech`" in error for error in result.errors))

    def test_extra_closing_paren_reports_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Extra Paren
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request"))
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(result.errors)

    def test_missing_boundary_closing_brace_reports_error(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Missing Brace
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System_Boundary(app_boundary, "App") {
    Container(api, "API", "Go", "Handles requests")
Rel(user, api, "Sends request", "HTTPS")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(result.errors)

    def test_unknown_relationship_macros_are_rejected(self):
        cases = [
            "RelRight(user, app, \"Sends request\")",
            "Relationship(user, app, \"Sends request\")",
            "RelX(user, app, \"Sends request\")",
        ]
        for statement in cases:
            with self.subTest(statement=statement):
                text = f"""
@startuml
!include <C4/C4_Context>
title System Context diagram for Unknown Relationship Macro
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
{statement}
@enduml
"""
                with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
                    handle.write(text.strip())
                    temp_path = Path(handle.name)

                result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
                self.assertTrue(result.errors)

    def test_unknown_element_named_arg_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Unknown Named Arg
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", tehcn="Go", $descr="Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unsupported named argument" in error for error in result.errors))

    def test_unknown_element_macro_is_error(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Hidden Typo
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", "Go", "Handles requests")
    Containerr(worker, "Worker", "Python", "Processes jobs")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown element `Containerr`; did you mean `Container`?" in error for error in result.errors))

    def test_keyword_arg_spacing_before_equals_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Spaced Keyword Arg
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", $techn = "Go", $descr="Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(result.errors)

    def test_container_baseshape_named_arg_is_allowed(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Base Shape
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", $techn="Go", $descr="Handles requests", $baseShape=EightSidedShape())
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_container_type_named_arg_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Invalid Type Arg
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", $type="foo", $techn="Go", $descr="Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unsupported named argument(s): `type`" in error for error in result.errors))

    def test_systemdb_baseshape_named_arg_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid Base Shape
LAYOUT_WITH_LEGEND()
SystemDb(db, "Database", $baseShape=EightSidedShape(), $descr="Stores data")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unsupported named argument(s): `baseShape`" in error for error in result.errors))

    def test_system_boundary_type_named_arg_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Invalid Boundary Type
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App", $type="foo") {
    Container(api, "API", "Go", "Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unsupported named argument(s): `type`" in error for error in result.errors))

    def test_element_missing_label_is_error(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Missing Label
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, $techn="Go", $descr="Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("missing a label" in error for error in result.errors))

    def test_fully_named_element_call_is_supported(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Fully Named Element
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container($alias=api, $label="API", $techn="Go", $descr="Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_dynamic_helpers_count_as_indexing(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for setIndex
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex(1)
Rel(user, app, "Sends request")
increment()
Rel(app, user, "Returns response")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertFalse(any("no indexed relationships" in warning for warning in result.warnings))

    def test_dynamic_helper_expression_counts_as_indexing(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for LastIndex
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", $index=LastIndex())
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertFalse(any("no indexed relationships" in warning for warning in result.warnings))

    def test_dynamic_helper_token_inside_label_does_not_count_as_indexing(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for Helper Token in Label
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Calls increment() helper", "HTTPS")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])
        self.assertTrue(any("no indexed relationships" in warning for warning in result.warnings))

    def test_dynamic_helpers_outside_dynamic_are_rejected(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for setIndex misuse
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex(1)
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("dynamic-only helper `setIndex` is not supported for `context` diagrams" in error for error in result.errors))

    def test_nested_setindex_outside_dynamic_is_rejected(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Nested Helper Misuse
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", $techn=setIndex(1))
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("dynamic-only helper `setIndex` is not supported for `context` diagrams" in error for error in result.errors))

    def test_index_helper_in_wrong_dynamic_argument_is_error_and_does_not_count(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for Wrong Helper Context
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", $techn=Index())
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`Index` is only supported inside relationship `index=`" in error for error in result.errors))
        self.assertTrue(any("no indexed relationships" in warning for warning in result.warnings))

    def test_startuml_inside_preamble_block_comment_does_not_open_block(self):
        text = """
/'
@startuml inside preamble comment
'/
@startuml
!include <C4/C4_Context>
title System Context diagram for Real Block
LAYOUT_WITH_LEGEND()
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_startuml_inside_between_block_comment_does_not_open_block(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for First Block
LAYOUT_WITH_LEGEND()
System(app, "App", "Handles")
@enduml

/'
@startuml inside between-block comment
'/

@startuml
!include <C4/C4_Context>
title System Context diagram for Second Block
LAYOUT_WITH_LEGEND()
System(api, "API", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_trailing_garbage_after_macro_call_is_error(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Trailing Garbage
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") {
    Container(api, "API", "Go", "Handles requests") blah
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_trailing_brace_after_non_structural_macro_is_error(self):
        cases = [
            """
@startuml
!include <C4/C4_Container>
title Container diagram for Invalid Brace
LAYOUT_WITH_LEGEND()
Container(api, "API", "Go", "Handles") {
}
@enduml
""",
            """
@startuml
!include <C4/C4_Context>
title System Context diagram for Invalid Brace
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Uses") {
}
@enduml
""",
        ]
        for text in cases:
            with self.subTest(text=text.splitlines()[1]):
                with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
                    handle.write(text.strip())
                    temp_path = Path(handle.name)

                result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
                self.assertTrue(any("unexpected trailing `{" in error for error in result.errors))

    def test_multiple_macro_calls_on_one_line_are_rejected(self):
        text = """
@startuml
!include <C4/C4_Container>
title Container diagram for Inline Multi Call
LAYOUT_WITH_LEGEND()
System_Boundary(app_boundary, "App") { Container(api, "API", "Go", "Handles requests") }
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_strict_mode_logic_is_available_via_cli_main(self):
        with mock.patch.object(VALIDATOR, "iter_paths", return_value=[INVALID_DIR / "missing_technology.puml"]):
            exit_code = VALIDATOR.main(["dummy", "--plantuml", "off", "--strict"])
        self.assertEqual(exit_code, 1)

    def test_explicit_plantuml_mode_warns_when_binary_missing(self):
        with mock.patch.object(VALIDATOR.shutil, "which", return_value=None):
            result = VALIDATOR.validate_file(VALID_DIR / "container.puml", plantuml_mode="on")
        self.assertEqual(result.errors, [])
        self.assertTrue(any("plantuml binary not available" in warning for warning in result.warnings))

    def test_multiblock_file_is_supported(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Test Suite
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System(app, "App", "Handles requests")
Rel(user, app, "Sends request")
@enduml

@startuml
!include <C4/C4_Container>
title Container diagram for Test Suite
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses the system")
System_Boundary(app_boundary, "App") {
    Container(api, "API", "Python", "Handles requests")
}
Rel(user, api, "Sends request", "HTTPS")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False) as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_enterpriseboundary_typo_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Typoed Boundary Macro
LAYOUT_WITH_LEGEND()
EnterpriseBoundary(org, "Org") {
    System(app, "App", "Handles")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown element `EnterpriseBoundary`; did you mean `Enterprise_Boundary`?" in error for error in result.errors))

    def test_deploymentnode_typo_is_error(self):
        text = """
@startuml
!include <C4/C4_Deployment>
title Deployment diagram for Typoed Node Macro
LAYOUT_WITH_LEGEND()
DeploymentNode(cloud, "AWS", "Cloud") {
    Container(api, "API", "Go", "Handles requests")
}
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unknown element `DeploymentNode`; did you mean `Deployment_Node`?" in error for error in result.errors))

    def test_enduml_inside_block_comment_does_not_split_block(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Comment EndUML
LAYOUT_WITH_LEGEND()
/'
@enduml inside comment
'/
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_enduml_inside_multiline_title_does_not_split_block(self):
        text = """
@startuml
!include <C4/C4_Context>
title
 System Context diagram for EndUML in Title
 @enduml inside title
end title
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_utf8_bom_before_startuml_is_supported(self):
        text = "\ufeff@startuml\n!include <C4/C4_Context>\ntitle System Context diagram for BOM\nLAYOUT_WITH_LEGEND()\nSystem(app, \"App\", \"Handles\")\n@enduml\n"
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text)
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_utf8_bom_multiblock_file_is_supported(self):
        text = "\ufeff@startuml\n!include <C4/C4_Context>\ntitle System Context diagram for BOM Block 1\nLAYOUT_WITH_LEGEND()\nSystem(app, \"App\", \"Handles\")\n@enduml\n\n@startuml\n!include <C4/C4_Context>\ntitle System Context diagram for BOM Block 2\nLAYOUT_WITH_LEGEND()\nSystem(api, \"API\", \"Handles\")\n@enduml\n"
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text)
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertEqual(result.errors, [])

    def test_trailing_garbage_after_layout_macro_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Layout Tail
LAYOUT_LEFT_RIGHT() blah
LAYOUT_WITH_LEGEND()
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_trailing_garbage_after_add_element_tag_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Tag Tail
LAYOUT_WITH_LEGEND()
AddElementTag("v1") blah
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_trailing_garbage_after_update_legend_title_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Update Legend Tail
LAYOUT_WITH_LEGEND()
UpdateLegendTitle("Legend") blah
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_trailing_garbage_after_setindex_is_error(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for Helper Tail
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex(1) blah
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("unexpected trailing content" in error for error in result.errors))

    def test_layout_macro_invalid_named_arg_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Layout Named Arg
LAYOUT_LEFT_RIGHT(foo=1)
LAYOUT_WITH_LEGEND()
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`LAYOUT_LEFT_RIGHT` uses unsupported named argument(s): `foo`" in error for error in result.errors))

    def test_show_floating_legend_invalid_named_arg_is_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for Floating Legend Named Arg
SHOW_FLOATING_LEGEND(foo=1)
System(app, "App", "Handles")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`SHOW_FLOATING_LEGEND` uses unsupported named argument(s): `foo`" in error for error in result.errors))

    def test_setindex_invalid_named_arg_is_error(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for setIndex Named Arg
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex(foo=1)
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`setIndex` uses unsupported named argument(s): `foo`" in error for error in result.errors))

    def test_increment_invalid_named_arg_is_error(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for increment Named Arg
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
increment(bar=2)
Rel(user, app, "Sends request")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`increment` uses unsupported named argument(s): `bar`" in error for error in result.errors))

    def test_top_level_helpers_accept_named_args_and_enforce_arity(self):
        cases = [
            {
                "name": "setIndex accepts $new_index",
                "text": """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for setIndex named arg
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex($new_index=1)
Rel(user, app, "Sends request")
@enduml
""",
                "expected_errors": [],
            },
            {
                "name": "UpdateLegendTitle accepts title",
                "text": """
@startuml
!include <C4/C4_Context>
title System Context diagram for Update Legend Title
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
UpdateLegendTitle(title="Legend")
Rel(user, app, "Sends request")
@enduml
""",
                "expected_errors": [],
            },
            {
                "name": "setIndex rejects mixed arity",
                "text": """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for setIndex mixed args
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
setIndex(1, new_index=2)
Rel(user, app, "Sends request")
@enduml
""",
                "expected_errors": ["`setIndex` expects exactly 1 argument(s), got 2"],
            },
            {
                "name": "increment rejects mixed arity",
                "text": """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for increment mixed args
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
increment(offset=2, 1)
Rel(user, app, "Sends request")
@enduml
""",
                "expected_errors": ["`increment` expects between 0 and 1 argument(s), got 2"],
            },
        ]

        for case in cases:
            with self.subTest(name=case["name"]):
                result = self.validate_text(case["text"])
                if not case["expected_errors"]:
                    self.assertEqual(result.errors, [])
                else:
                    self.assertEqual(len(result.errors), 1)
                    self.assertTrue(any(case["expected_errors"][0] in error for error in result.errors))

    def test_element_named_arg_spacing_before_equals_reports_single_error(self):
        text = """
@startuml
!include <C4/C4_Dynamic>
title Dynamic diagram for element spacing
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles", descr = "Handles requests")
Rel(user, app, "Sends request")
@enduml
"""
        result = self.validate_text(text)
        matching_errors = [error for error in result.errors if "spaces before `=`" in error]
        self.assertEqual(len(matching_errors), 1)
        self.assertTrue(any("`System` uses named argument(s) with spaces before `=`: `descr`" in error for error in matching_errors))

    def test_relationship_named_arg_spacing_before_equals_reports_single_error(self):
        text = """
@startuml
!include <C4/C4_Context>
title System Context diagram for relationship spacing
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", $techn = "HTTPS")
@enduml
"""
        result = self.validate_text(text)
        matching_errors = [error for error in result.errors if "spaces before `=`" in error]
        self.assertEqual(len(matching_errors), 1)
        self.assertTrue(any("`Rel` uses named argument(s) with spaces before `=`: `techn`" in error for error in matching_errors))

    def test_c4_sequence_include_reports_explicit_out_of_scope_error(self):
        text = """
@startuml
!include <C4/C4_Sequence>
title Sequence diagram for Unsupported Surface
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Rel(user, app, "Sends request", $index=1, $rel="->")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`C4_Sequence.puml` is out of scope for this skill" in error for error in result.errors))

    def test_show_index_reports_sequence_out_of_scope_error(self):
        text = """
@startuml
!include <C4/C4_Sequence>
title Sequence diagram for SHOW_INDEX
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
SHOW_INDEX()
Rel(user, app, "Sends request", $index=1, $rel="->")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`SHOW_INDEX` belongs to `C4_Sequence.puml`" in error for error in result.errors))

    def test_show_foot_boxes_reports_sequence_out_of_scope_error(self):
        text = """
@startuml
!include <C4/C4_Sequence>
title Sequence diagram for SHOW_FOOT_BOXES
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
SHOW_FOOT_BOXES()
Rel(user, app, "Sends request", $index=1, $rel="->")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`SHOW_FOOT_BOXES` belongs to `C4_Sequence.puml`" in error for error in result.errors))

    def test_boundary_end_reports_sequence_out_of_scope_error(self):
        text = """
@startuml
!include <C4/C4_Sequence>
title Sequence diagram for Boundary_End
LAYOUT_WITH_LEGEND()
Person(user, "User", "Uses")
System(app, "App", "Handles")
Boundary_End()
Rel(user, app, "Sends request", $index=1, $rel="->")
@enduml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as handle:
            handle.write(text.strip())
            temp_path = Path(handle.name)

        result = VALIDATOR.validate_file(temp_path, plantuml_mode="off")
        self.assertTrue(any("`Boundary_End` belongs to `C4_Sequence.puml`" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
