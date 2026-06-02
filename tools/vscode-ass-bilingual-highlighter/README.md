# Autosub ZH ASS Bilingual Highlighter

Local VS Code syntax highlighting for bilingual `.ass` and `.ssa` subtitle files.

## What It Highlights

- `Start` time and `End` time in different colors.
- Chinese dialogue text when the `Style` field is `Default`, `Chinese`, `ChineseSmall`, `ZH`, `zh`, or `中文`.
- English dialogue text when the `Style` field is `EnglishSmall`, `English`, `EN`, `en`, or `英文`.
- ASS override tags such as `{\i1}` and subtitle line breaks such as `\N`.

## Install

Run this from the repository root:

```powershell
.\tools\vscode-ass-bilingual-highlighter\install.ps1
```

Then reload VS Code and reopen an `.ass` or `.ssa` file.

## Change Colors

The workspace color rules live in `.vscode/settings.json`. Edit the hex colors under `editor.tokenColorCustomizations.textMateRules` if you want a different palette.
