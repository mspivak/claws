from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_terraform_declares_status_approved_ssm():
    main_tf = (REPO_ROOT / "terraform" / "main.tf").read_text()
    assert "github_status_approved" in main_tf
    assert "/github/status-approved" in main_tf


def test_user_data_exports_status_approved():
    user_data = (REPO_ROOT / "terraform" / "user_data.sh").read_text()
    assert "CLAWS_STATUS_APPROVED=$(get_param github/status-approved)" in user_data


def test_readme_lists_approved_status():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "approved" in readme.lower()


def test_plan_lists_approved_status():
    plan = (REPO_ROOT / "PLAN.md").read_text()
    assert "status-approved" in plan
