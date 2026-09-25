import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from PySide6.QtCore import QSettings

from services.nc_communication import build_email

PROVEDORES = {
    "Gmail": ("smtp.gmail.com", 587),
    "Outlook / Office 365": ("smtp.office365.com", 587),
    "Outro": ("", 587),
}

_SETTINGS_KEYS = ("provedor", "servidor", "porta", "remetente", "nome", "copia")


@dataclass
class EmailConfig:
    """SMTP settings; the password is never stored here."""

    provedor: str = "Gmail"
    servidor: str = "smtp.gmail.com"
    porta: int = 587
    remetente: str = ""
    nome: str = ""
    copia: str = ""

    @property
    def completa(self):
        return bool(self.servidor and self.porta and self.remetente)


def _settings():
    return QSettings("pyComformity", "pyComformity")


def load_config():
    settings = _settings()
    config = EmailConfig()
    for key in _SETTINGS_KEYS:
        value = settings.value(f"email/{key}")
        if value is not None:
            setattr(config, key, int(value) if key == "porta" else str(value))
    return config


def save_config(config):
    settings = _settings()
    for key in _SETTINGS_KEYS:
        settings.setValue(f"email/{key}", getattr(config, key))


def build_message(config, nc, pdf_paths):
    assunto, corpo = build_email(nc, pdf_paths)

    message = EmailMessage()
    message["Subject"] = assunto
    message["From"] = formataddr((config.nome, config.remetente))
    message["To"] = ", ".join(nc.destinatarios())
    if config.copia:
        message["Cc"] = config.copia
    message.set_content(corpo)

    for pdf_path in pdf_paths:
        pdf = Path(pdf_path)
        message.add_attachment(
            pdf.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename=pdf.name,
        )
    return message


def _connect(config, senha, timeout):
    context = ssl.create_default_context()
    if config.porta == 465:
        server = smtplib.SMTP_SSL(
            config.servidor, config.porta, context=context, timeout=timeout
        )
    else:
        server = smtplib.SMTP(config.servidor, config.porta, timeout=timeout)
        server.starttls(context=context)
    server.login(config.remetente, senha)
    return server


def test_login(config, senha, timeout=20):
    with _connect(config, senha, timeout):
        pass


def send_message(config, senha, message, timeout=30):
    with _connect(config, senha, timeout) as server:
        server.send_message(message)


def friendly_error(error):
    """Turns SMTP exceptions into a message the user can act on."""
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "Usuário ou senha recusados pelo servidor.\n\n"
            "Gmail: use uma senha de app (precisa da verificação em duas "
            "etapas ativa), não a senha normal da conta.\n"
            "Outlook: a organização precisa liberar SMTP AUTH para a conta; "
            "contas pessoais do outlook.com podem bloquear esse tipo de login."
        )
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "O servidor recusou o destinatário. Confira o e-mail do responsável."
    # SMTPException is an OSError subclass, so it must be checked first.
    if isinstance(error, smtplib.SMTPException):
        return f"O servidor de e-mail recusou o envio:\n{error}"
    if isinstance(error, OSError):
        return f"Não consegui conectar ao servidor de e-mail:\n{error}"
    return str(error)
