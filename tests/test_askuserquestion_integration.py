#!/usr/bin/env python3
"""
Integration test for AskUserQuestion bug fixes:
- Bug #1: Overview parameter is passed through handler signature
- Bug #2: Option text rendering with fallback keys (label, text, option, description, help, hint)
- Bug #3: Input validation handles malformed data gracefully
"""
import sys
sys.path.insert(0, 'src')

from harness.ui.terminal import TerminalUI
from harness.ui.renderers import OutputRenderer
from harness.orchestration.llm_client import LLMClient


def test_bug1_overview_parameter():
    """Test Bug #1: Overview parameter flows through handler signature."""
    print("\n[TEST 1] Bug #1: Overview Parameter Integration")
    print("=" * 70)

    ui = TerminalUI(llm_client=LLMClient())

    # Check handler signature accepts overview parameter
    import inspect
    sig = inspect.signature(ui.handle_ask_user_question)
    params = list(sig.parameters.keys())

    assert 'overview' in params, f"overview param missing! Got: {params}"
    assert sig.parameters['overview'].default == "", f"overview should default to empty string"
    print("  ✓ Handler signature includes 'overview' parameter with default ''")

    # Verify overview reaches rendering state
    questions = [{"question": "Pick one", "options": [{"title": "A"}]}]
    state = {
        "questions": questions,
        "multi_select": False,
        "current_tab_index": 0,
        "current_focus_index": 0,
        "selections": {},
        "custom_focus": None,
        "custom_values": {},
        "submitted": False,
        "answers": {},
        "overview": "System Overview: Please make a selection below",
    }

    # Render with overview
    rendered = str(OutputRenderer.render_ask_user_questions(state, width=80))

    assert "System Overview" in rendered, "Overview text not rendered in UI!"
    print("  ✓ Overview text appears in rendered UI output")
    print(f"\n  [RENDERED OUTPUT SAMPLE]:\n{rendered[:400]}...\n")


def test_bug2_option_text_fallback():
    """Test Bug #2: Option title/detail rendering with multi-key fallback."""
    print("\n[TEST 2] Bug #2: Option Text Rendering Fallback Chain")
    print("=" * 70)

    test_cases = [
        {
            "name": "Standard 'title' key",
            "option": {"title": "Standard Title"},
            "expect_title": "Standard Title",
        },
        {
            "name": "'label' fallback (1st level)",
            "option": {"label": "Option Label"},
            "expect_title": "Option Label",
        },
        {
            "name": "'text' fallback (2nd level)",
            "option": {"text": "Text Field"},
            "expect_title": "Text Field",
        },
        {
            "name": "'option' fallback (3rd level)",
            "option": {"option": "Option Value"},
            "expect_title": "Option Value",
        },
        {
            "name": "'description' detail fallback",
            "option": {
                "title": "Main Title",
                "description": "This is the description",
            },
            "expect_title": "Main Title",
            "expect_detail": "This is the description",
        },
        {
            "name": "'help' detail fallback",
            "option": {
                "title": "Config Option",
                "help": "Set this to enable feature X",
            },
            "expect_title": "Config Option",
            "expect_detail": "Set this to enable feature X",
        },
        {
            "name": "'hint' detail fallback",
            "option": {
                "title": "Advanced",
                "hint": "Hint: use with caution",
            },
            "expect_title": "Advanced",
            "expect_detail": "Hint: use with caution",
        },
    ]

    for case in test_cases:
        state = {
            "questions": [{
                "question": "Test Question",
                "options": [case["option"]]
            }],
            "multi_select": False,
            "current_tab_index": 0,
            "current_focus_index": 0,
            "selections": {},
            "custom_focus": None,
            "custom_values": {},
            "submitted": False,
            "answers": {},
            "overview": "",
        }

        rendered = str(OutputRenderer.render_ask_user_questions(state, width=80))

        # Check title is rendered
        assert case["expect_title"] in rendered, \
            f"FAIL [{case['name']}]: Expected title '{case['expect_title']}' not found"
        print(f"  ✓ {case['name']}: title rendered correctly")

        # Check detail if expected
        if "expect_detail" in case:
            assert case["expect_detail"] in rendered, \
                f"FAIL [{case['name']}]: Expected detail '{case['expect_detail']}' not found"
            print(f"    └─ detail also rendered correctly")


def test_bug3_input_validation():
    """Test Bug #3: Input validation handles malformed questions gracefully."""
    print("\n[TEST 3] Bug #3: Input Validation for Malformed Data")
    print("=" * 70)

    ui = TerminalUI(llm_client=LLMClient())

    test_cases = [
        {
            "name": "None input (missing questions)",
            "input": None,
            "should_have_fallback": True,
        },
        {
            "name": "Empty list",
            "input": [],
            "should_have_fallback": True,
        },
        {
            "name": "String instead of list (wrong type)",
            "input": "not a list",
            "should_have_fallback": True,
        },
        {
            "name": "Non-dict items in list",
            "input": [None, "string", 123],
            "should_have_fallback": True,
        },
        {
            "name": "Options as string instead of list",
            "input": [{"question": "Q", "options": "invalid"}],
            "should_normalize_options": True,
        },
        {
            "name": "Valid question (should pass through)",
            "input": [{"question": "Real Q", "options": [{"title": "A"}]}],
            "should_preserve": True,
        },
    ]

    for case in test_cases:
        try:
            result = ui._validate_questions(case["input"])

            # Should always return a non-empty list
            assert isinstance(result, list), \
                f"FAIL [{case['name']}]: Result not a list, got {type(result)}"
            assert len(result) > 0, \
                f"FAIL [{case['name']}]: Result is empty list"

            if case.get("should_have_fallback"):
                # Should contain the default safe question
                assert any("No question provided" in str(q) for q in result), \
                    f"FAIL [{case['name']}]: Default fallback not applied"
                print(f"  ✓ {case['name']}: gracefully defaults to safe question")

            if case.get("should_normalize_options"):
                # Should have normalized bad options to []
                assert result[0].get("options") == [], \
                    f"FAIL [{case['name']}]: Options not normalized to []"
                print(f"  ✓ {case['name']}: malformed options normalized to []")

            if case.get("should_preserve"):
                # Should preserve the original valid question
                assert result[0].get("question") == "Real Q", \
                    f"FAIL [{case['name']}]: Valid question not preserved"
                assert len(result[0].get("options", [])) == 1, \
                    f"FAIL [{case['name']}]: Options not preserved"
                print(f"  ✓ {case['name']}: valid question passed through unchanged")

        except Exception as e:
            print(f"  ✗ {case['name']}: {e}")
            raise


def test_full_integration_all_fixes_together():
    """Integration test: All 3 fixes working together in a real rendering scenario."""
    print("\n[TEST 4] Full Integration: All 3 Fixes Working Together")
    print("=" * 70)

    ui = TerminalUI(llm_client=LLMClient())

    # Create questions with mixed key styles (testing fallbacks)
    raw_questions = [
        {
            "question": "Select your preference",
            "options": [
                {"label": "Alice"},                                    # Uses label fallback
                {"text": "Bob"},                                       # Uses text fallback
                {"title": "Charlie", "description": "The Developer"},  # Uses description fallback
                {"option": "Diana", "help": "Help Text"},              # Uses option + help fallback
                {"title": "Eve", "hint": "A Hint"},                    # Uses hint fallback
            ]
        }
    ]

    # Step 1: Validate (Bug #3 validation)
    validated = ui._validate_questions(raw_questions)
    assert len(validated) == 1, "Should have 1 question after validation"
    assert len(validated[0]["options"]) == 5, "Should have 5 options after validation"
    print("  ✓ Step 1: Input validation passed - questions structure confirmed")

    # Step 2: Create render state with overview (Bug #1 overview)
    state = {
        "questions": validated,
        "overview": "Please select your favorite character",  # Bug #1: overview parameter
        "multi_select": False,
        "current_tab_index": 0,
        "current_focus_index": 0,
        "selections": {},
        "custom_focus": None,
        "custom_values": {},
        "submitted": False,
        "answers": {},
    }
    print("  ✓ Step 2: State created with overview parameter")

    # Step 3: Render (Bug #2 option text fallback)
    rendered = str(OutputRenderer.render_ask_user_questions(state, width=80))

    # Verify ALL fixes are present in rendered output
    print("  ✓ Step 3: Rendering complete. Verifying output...")

    # Bug #1: Overview should be rendered
    assert "Please select your favorite character" in rendered, \
        "Bug #1 FAILED: Overview not rendered"
    print("    └─ Bug #1 ✓: Overview text appears in UI")

    # Bug #2: All option text fallbacks should work
    assertions = [
        ("Alice", "label fallback"),
        ("Bob", "text fallback"),
        ("Charlie", "title rendering"),
        ("The Developer", "description fallback"),
        ("Diana", "option fallback"),
        ("Help Text", "help fallback"),
        ("Eve", "title preserved"),
        ("A Hint", "hint fallback"),
    ]

    for expected, context in assertions:
        assert expected in rendered, f"Bug #2 FAILED: {context} - '{expected}' not found"
        print(f"    └─ Bug #2 ✓: {context} rendered")

    # Bug #3: Validation ensured we got here without errors
    print("    └─ Bug #3 ✓: Validation handled mixed input without crashing")

    print(f"\n  [FULL RENDERED UI OUTPUT]:\n{rendered}\n")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("ASKUSERQUESTION BUG FIX INTEGRATION TESTS")
    print("Testing 3 critical bugs with end-to-end rendering verification")
    print("=" * 70)

    try:
        test_bug1_overview_parameter()
        test_bug2_option_text_fallback()
        test_bug3_input_validation()
        test_full_integration_all_fixes_together()

        print("\n" + "=" * 70)
        print("ALL INTEGRATION TESTS PASSED ✓✓✓")
        print("=" * 70)
        print("\nVerified Bug Fixes:")
        print("  [✓] Bug #1: Overview parameter flows through to rendering")
        print("  [✓] Bug #2: Option text fallback chain works (title/label/text/option)")
        print("  [✓] Bug #2: Detail fallback chain works (detail/description/help/hint)")
        print("  [✓] Bug #3: Input validation handles all malformed data gracefully")
        print("  [✓] FULL INTEGRATION: All fixes work together with beautiful UI rendering\n")

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
