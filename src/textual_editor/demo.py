from textual.app import App, ComposeResult
from textual.widgets import Footer

from textual_editor import Editor


class EditorApp(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def compose(self) -> ComposeResult:
        yield Editor(path="vim", content='print("Hello, World!")', language="py")
        yield Footer()

def main():
    app = EditorApp()
    app.run()

if __name__ == "__main__":
    main()
