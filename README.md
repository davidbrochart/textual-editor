# textual-editor

A [Textual](https://github.com/Textualize/textual) widget embedding an external editor.

This is similar to a [TextArea](https://textual.textualize.io/widgets/text_area), but instead of reimplementing all the features of an editor,
the idea is to run a real editor (e.g. Vim) and connect it to a [terminal emulator](https://github.com/selectel/pyte).

See [the demo](https://github.com/davidbrochart/textual-editor/blob/master/src/textual_editor/demo.py) and try it with:

```bash
uvx textual-editor
```


