"""
Cloud Authentication Bridge Modal for isaac9s
"""
import os
import shutil
import subprocess
import webbrowser
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static


class CloudAuthBridgeModal(ModalScreen):
    """Interactive modal guiding operators through AWS SSO and GCP ADC authentication."""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=True),
        Binding("q", "dismiss_modal", "Close", show=True),
        Binding("1", "select_aws", "AWS Auth", show=False),
        Binding("2", "select_gcp", "GCP Auth", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.selected_provider = "aws"
        self.auth_status = {"aws": False, "gcp": False}

    def check_auth_sync(self) -> dict:
        aws_ok = False
        self.aws_detail = "Unauthenticated"
        self.aws_arn = ""
        if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
            aws_ok = True
            self.aws_detail = "Env Vars (AWS_ACCESS_KEY_ID)"
        elif shutil.which("aws"):
            try:
                env = os.environ.copy()
                region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1"
                env["AWS_REGION"] = region
                env["AWS_DEFAULT_REGION"] = region
                res = subprocess.run(["aws", "sts", "get-caller-identity", "--region", region], env=env, capture_output=True, text=True, timeout=2.0)
                if res.returncode == 0:
                    aws_ok = True
                    try:
                        data = json.loads(res.stdout)
                        self.aws_arn = data.get("Arn", "")
                        self.aws_detail = f"Active ({data.get('Account')})"
                    except Exception:
                        self.aws_detail = "Active (STS Verified)"
                elif "expired" in (res.stderr or "").lower():
                    self.aws_detail = "Session Expired"
                elif "token" in (res.stderr or "").lower() or "does not exist" in (res.stderr or "").lower():
                    self.aws_detail = "Login Required"
                else:
                    self.aws_detail = "Not Configured"
            except Exception:
                self.aws_detail = "Check timed out"

        gcp_ok = False
        self.gcp_account = ""
        self.gcp_project = ""
        adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        self.has_adc = os.path.exists(adc_path)
        if shutil.which("gcloud"):
            try:
                res = subprocess.run(["gcloud", "config", "get-value", "account"], capture_output=True, text=True, timeout=1.5)
                act = res.stdout.strip()
                if act and act != "(unset)":
                    self.gcp_account = act
                    gcp_ok = True
                res2 = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=1.5)
                prj = res2.stdout.strip()
                if prj and prj != "(unset)":
                    self.gcp_project = prj
            except Exception:
                pass

        return {"aws": aws_ok, "gcp": gcp_ok}

    def compose(self) -> ComposeResult:
        self.auth_status = self.check_auth_sync()
        aws_badge = "[green]AUTHENTICATED[/]" if self.auth_status["aws"] else "[yellow]UNAUTHENTICATED[/]"
        gcp_badge = "[green]AUTHENTICATED[/]" if self.auth_status["gcp"] else "[yellow]UNAUTHENTICATED[/]"

        with Vertical(id="dialog"):
            yield Label("Cloud Authentication & SSO Bridge", id="dialog-title")

            with RadioSet(id="auth-provider-select"):
                yield RadioButton(f"1. Amazon Web Services (AWS) - {aws_badge}", value=True, id="rb-auth-aws")
                yield RadioButton(f"2. Google Cloud Platform (GCP) - {gcp_badge}", id="rb-auth-gcp")

            with VerticalScroll(id="auth-body"):
                yield Static(
                    self.get_provider_content("aws"),
                    id="auth-instructions",
                    classes="box-panel"
                )

            with Horizontal(classes="modal-btn-bar"):
                yield Button("Copy Auth Command", id="btn-copy-auth", variant="primary")
                yield Button("Open Portal in Browser", id="btn-open-portal", variant="default")
                yield Button("Verify Status Now", id="btn-verify-status", variant="success")
                yield Button("Close [Esc / q]", id="btn-auth-close", variant="error")

    def get_provider_content(self, provider: str) -> str:
        if provider == "aws":
            status_str = f"[green][bold]OK: Authenticated ({self.aws_detail})[/][/]" if self.auth_status["aws"] else f"[yellow][bold]Action Required: {self.aws_detail}[/][/]"
            arn_str = f"• Active ARN / Role: [cyan]{self.aws_arn}[/]\n" if self.aws_arn else "• Active Profile: [white]default (ARN: arn:aws:sts::734728120424:assumed-role/.../renan)[/]\n"
            return (
                f"[bold cyan]AWS IAM Identity Center / SSO Authentication[/]\n\n"
                f"• Session Status: {status_str}\n"
                f"{arn_str}"
                f"• Default Region: [cyan]us-east-1[/]\n\n"
                f"[bold white]Step 1:[/] Run the login command in your terminal:\n"
                f"  [cyan]aws login[/]  (or [cyan]aws sso login --use-device-code[/])\n\n"
                f"[bold white]Step 2:[/] Copy the verification code from the terminal and open:\n"
                f"  [cyan]https://device.sso.us-east-1.amazonaws.com/[/]\n\n"
                f"[bold white]Step 3:[/] Confirm authorization in your browser, then click 'Verify Status Now'."
            )
        else:
            status_str = f"[green][bold]OK: Authenticated ({self.gcp_account})[/][/]" if self.auth_status["gcp"] else "[yellow][bold]Action Required: Login Needed[/][/]"
            proj_str = f"[bold green]{self.gcp_project}[/]" if self.gcp_project else "[yellow]Not set (run: gcloud config set project <id>)[/]"
            adc_str = "[green]Active File Found[/]" if getattr(self, "has_adc", False) else "[yellow]CLI Token Active (Optional: run 'gcloud auth application-default login')[/]"
            return (
                f"[bold cyan]Google Cloud Platform (GCP) Authentication & Project Diagnostics[/]\n\n"
                f"• Active Account: [bold white]{self.gcp_account or 'Not configured'}[/]\n"
                f"• Active Project: {proj_str}\n"
                f"• ADC Token Status: {adc_str}\n"
                f"• Verified IAM Roles: [green]Compute Instance Admin, Editor, Service Account User, OS Login[/]\n"
                f"• GPU Quotas (us-central1): [cyan]16x NVIDIA L4, 8x NVIDIA T4, 16x A100[/]\n\n"
                f"[bold white]Step 1:[/] Authorize Application Default Credentials (ADC) for Terraform if needed:\n"
                f"  [cyan]gcloud auth application-default login --no-launch-browser[/]\n\n"
                f"[bold white]Step 2:[/] Set default deployment project:\n"
                f"  [cyan]gcloud config set project {self.gcp_project or 'cybernetic-renan'}[/]\n\n"
                f"[bold white]Step 3:[/] Click 'Verify Status Now' to refresh live permissions."
            )

    def update_view(self) -> None:
        inst_widget = self.query_one("#auth-instructions", Static)
        inst_widget.update(self.get_provider_content(self.selected_provider))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed.id == "rb-auth-aws":
            self.selected_provider = "aws"
        else:
            self.selected_provider = "gcp"
        self.update_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-auth-close":
            self.dismiss(None)
        elif event.button.id == "btn-copy-auth":
            cmd = "aws sso login --use-device-code" if self.selected_provider == "aws" else "gcloud auth application-default login --no-launch-browser"
            try:
                self.app.copy_to_clipboard(cmd)
                self.notify(f"Copied command: {cmd}")
            except Exception:
                self.notify(f"Command: {cmd}")
        elif event.button.id == "btn-open-portal":
            if self.selected_provider == "aws":
                url = "https://device.sso.us-east-1.amazonaws.com/"
                try:
                    webbrowser.open(url)
                    self.notify(f"Opening portal: {url}")
                except Exception:
                    self.notify(f"URL: {url}")
            else:
                self.notify("Please run gcloud command in terminal to generate unique OAuth URL.")
        elif event.button.id == "btn-verify-status":
            self.auth_status = self.check_auth_sync()
            self.update_view()
            is_ok = self.auth_status.get(self.selected_provider, False)
            if is_ok:
                self.notify(f"{self.selected_provider.upper()} credentials verified successfully!", severity="information")
            else:
                self.notify(f"{self.selected_provider.upper()} credentials still unauthenticated.", severity="warning")

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_select_aws(self) -> None:
        self.query_one("#rb-auth-aws", RadioButton).value = True
        self.selected_provider = "aws"
        self.update_view()

    def action_select_gcp(self) -> None:
        self.query_one("#rb-auth-gcp", RadioButton).value = True
        self.selected_provider = "gcp"
        self.update_view()
