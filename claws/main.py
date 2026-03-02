import typer
from claws.commands import init, setup_telegram, setup_github, status, destroy

app = typer.Typer(no_args_is_help=True)

app.command("init")(init.run)
app.command("setup-telegram")(setup_telegram.run)
app.command("setup-github")(setup_github.run)
app.command("status")(status.run)
app.command("destroy")(destroy.run)
