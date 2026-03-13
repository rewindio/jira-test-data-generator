"""
Unit tests for CLI entry points in jira_data_generator.py and jira_user_generator.py.
"""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest


def create_mock_file_handler():
    """Create a mock FileHandler with proper level attribute."""
    mock_handler = MagicMock()
    mock_handler.level = logging.INFO
    mock_handler.setLevel = MagicMock()
    mock_handler.setFormatter = MagicMock()
    return mock_handler


class TestJiraDataGeneratorCLI:
    """Tests for jira_data_generator CLI."""

    def test_main_missing_token_exits(self):
        """Test main exits when no token provided."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--prefix",
            "TEST",
            "--count",
            "10",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {}, clear=True):
                with patch("jira_data_generator.load_dotenv"):
                    from jira_data_generator import main

                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1

    def test_main_dry_run_sync(self, tmp_path):
        """Test main with dry-run in sync mode."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "10",
            "--dry-run",
            "--no-async",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    # Should complete without error
                    main()

    def test_main_dry_run_async(self, tmp_path):
        """Test main with dry-run in async mode."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "10",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_verbose(self):
        """Test main with verbose flag."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--dry-run",
            "--verbose",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_issues_only(self):
        """Test main with issues-only flag."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--dry-run",
            "--issues-only",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_project_override(self):
        """Test main with project override."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "10",
            "--projects",
            "2",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_concurrency(self):
        """Test main with custom concurrency."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--concurrency",
            "10",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_request_delay(self):
        """Test main with request delay."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--request-delay",
            "0.1",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    from jira_data_generator import main

                    main()

    def test_main_with_size_buckets(self):
        """Test main with different size buckets."""
        for size in ["small", "medium", "large", "xlarge"]:
            test_args = [
                "jira_data_generator.py",
                "--url",
                "https://test.atlassian.net",
                "--email",
                "test@example.com",
                "--token",
                "test-token",
                "--prefix",
                "TEST",
                "--count",
                "5",
                "--size",
                size,
                "--dry-run",
                "--no-checkpoint",
            ]

            with patch.object(sys, "argv", test_args):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        from jira_data_generator import main

                        main()

    def test_main_token_from_env(self):
        """Test main gets token from environment."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_API_TOKEN": "env-token"}):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        from jira_data_generator import main

                        main()

    def test_main_resume_no_checkpoint(self, tmp_path):
        """Test main with --resume but no checkpoint exists."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "test@example.com",
            "--token",
            "test-token",
            "--prefix",
            "NONEXISTENT",
            "--count",
            "5",
            "--dry-run",
            "--resume",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_data_generator.load_dotenv"):
                with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                    with patch("jira_data_generator.CheckpointManager") as MockCheckpoint:
                        mock_cm = MagicMock()
                        mock_cm.find_existing_checkpoint.return_value = None
                        mock_cm.checkpoint = None
                        MockCheckpoint.return_value = mock_cm

                        from jira_data_generator import main

                        main()

    def test_main_url_email_from_env(self):
        """Test main gets URL and email from environment variables."""
        test_args = [
            "jira_data_generator.py",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--dry-run",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict(
                "os.environ",
                {"JIRA_URL": "https://env.atlassian.net", "JIRA_EMAIL": "env@example.com"},
            ):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        from jira_data_generator import main

                        main()

    def test_main_cli_args_override_env(self):
        """Test CLI --url/--email take precedence over environment variables."""
        test_args = [
            "jira_data_generator.py",
            "--url",
            "https://cli.atlassian.net",
            "--email",
            "cli@example.com",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
            "--dry-run",
            "--no-async",
            "--no-checkpoint",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict(
                "os.environ",
                {"JIRA_URL": "https://env.atlassian.net", "JIRA_EMAIL": "env@example.com"},
            ):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        with patch("jira_data_generator.JiraDataGenerator") as MockGen:
                            mock_gen = MagicMock()
                            MockGen.return_value = mock_gen

                            from jira_data_generator import main

                            main()

                            # Verify CLI args were used, not env vars
                            call_kwargs = MockGen.call_args[1]
                            assert call_kwargs["jira_url"] == "https://cli.atlassian.net"
                            assert call_kwargs["email"] == "cli@example.com"

    def test_main_missing_url_exits(self):
        """Test main exits when no URL provided via CLI or env."""
        test_args = [
            "jira_data_generator.py",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com"}, clear=True):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        from jira_data_generator import main

                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1

    def test_main_missing_email_exits(self):
        """Test main exits when no email provided via CLI or env."""
        test_args = [
            "jira_data_generator.py",
            "--token",
            "test-token",
            "--prefix",
            "TEST",
            "--count",
            "5",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_URL": "https://env.atlassian.net"}, clear=True):
                with patch("jira_data_generator.load_dotenv"):
                    with patch("jira_data_generator.logging.FileHandler", return_value=create_mock_file_handler()):
                        from jira_data_generator import main

                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 1


class TestJiraUserGeneratorCLI:
    """Tests for jira_user_generator CLI."""

    def test_main_missing_token_exits(self):
        """Test main exits when no token provided."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--base-email",
            "test@example.com",
            "--users",
            "3",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {}, clear=True):
                with patch("jira_user_generator.load_dotenv"):
                    from jira_user_generator import main

                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1

    def test_main_dry_run(self):
        """Test main with dry-run."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "3",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_user_generator.load_dotenv"):
                from jira_user_generator import main

                main()

    def test_main_with_groups(self):
        """Test main with groups."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--groups",
            "TestGroup1",
            "TestGroup2",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_user_generator.load_dotenv"):
                from jira_user_generator import main

                main()

    def test_main_with_verbose(self):
        """Test main with verbose flag."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--verbose",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_user_generator.load_dotenv"):
                from jira_user_generator import main

                main()

    def test_main_with_user_prefix(self):
        """Test main with custom user prefix."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--user-prefix",
            "TestUser",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_user_generator.load_dotenv"):
                from jira_user_generator import main

                main()

    def test_main_with_products(self):
        """Test main with custom products."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--products",
            "jira-software",
            "jira-servicedesk",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("jira_user_generator.load_dotenv"):
                from jira_user_generator import main

                main()

    def test_main_token_from_env(self):
        """Test main gets token from environment."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://test.atlassian.net",
            "--email",
            "admin@example.com",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_API_TOKEN": "env-token"}):
                with patch("jira_user_generator.load_dotenv"):
                    from jira_user_generator import main

                    main()

    def test_main_url_email_from_env(self):
        """Test main gets URL and email from environment variables."""
        test_args = [
            "jira_user_generator.py",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict(
                "os.environ",
                {
                    "JIRA_URL": "https://env.atlassian.net",
                    "JIRA_EMAIL": "env@example.com",
                    "JIRA_API_TOKEN": "env-token",
                },
            ):
                with patch("jira_user_generator.load_dotenv"):
                    from jira_user_generator import main

                    main()

    def test_main_cli_args_override_env(self):
        """Test CLI --url/--email take precedence over environment variables."""
        test_args = [
            "jira_user_generator.py",
            "--url",
            "https://cli.atlassian.net",
            "--email",
            "cli@example.com",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict(
                "os.environ",
                {"JIRA_URL": "https://env.atlassian.net", "JIRA_EMAIL": "env@example.com"},
            ):
                with patch("jira_user_generator.load_dotenv"):
                    with patch("jira_user_generator.JiraUserGenerator") as MockGen:
                        mock_gen = MagicMock()
                        MockGen.return_value = mock_gen

                        from jira_user_generator import main

                        main()

                        # Verify CLI args were used, not env vars
                        call_kwargs = MockGen.call_args[1]
                        assert call_kwargs["jira_url"] == "https://cli.atlassian.net"
                        assert call_kwargs["email"] == "cli@example.com"

    def test_main_missing_url_exits(self):
        """Test main exits when no URL provided via CLI or env."""
        test_args = [
            "jira_user_generator.py",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com"}, clear=True):
                with patch("jira_user_generator.load_dotenv"):
                    from jira_user_generator import main

                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1

    def test_main_missing_email_exits(self):
        """Test main exits when no email provided via CLI or env."""
        test_args = [
            "jira_user_generator.py",
            "--token",
            "test-token",
            "--base-email",
            "test@example.com",
            "--users",
            "2",
        ]

        with patch.object(sys, "argv", test_args):
            with patch.dict("os.environ", {"JIRA_URL": "https://env.atlassian.net"}, clear=True):
                with patch("jira_user_generator.load_dotenv"):
                    from jira_user_generator import main

                    with pytest.raises(SystemExit) as exc_info:
                        main()
                    assert exc_info.value.code == 1
