from cyclopts import App
from textual.app import App as TextualApp, ComposeResult
from textual.widgets import Footer

from textual_editor import Editor

app = App()


@app.default
def main(
    path: str = "vim",
    content: str = 'print("Hello, World!")',
    language: str = "py",
) -> None:
    app = EditorApp(path, content, language)
    app.run()


class EditorApp(TextualApp):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def __init__(
        self,
        path: str,
        content: str,
        language: str,
    ) -> None:
        super().__init__()
        self._path = path
        self._content = content
        self._language = language

    def compose(self) -> ComposeResult:
        yield Editor(path=self._path, content=self._content, language=self._language)
        yield Footer()


if __name__ == "__main__":
    app()
