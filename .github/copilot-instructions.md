# Repository instructions

- Analyze before modifying files. Keep changes small and focused.
- Do not commit, push, merge, tag, delete branches or rewrite Git history unless the
  user asks for it explicitly.
- Never modify files outside the workspace. Never overwrite files under `samples/`.
- Run `pytest` after behavioural changes; keep `ruff check src tests` clean.
- Architecture is vector-native: geometry comes only from PDF vector paths.
  Rasterization is allowed only for validation and previews, never to build geometry.
- Symbol recognition is data-driven: change `config/*.toml` rules, not code, to adapt
  to a new map.
- Outputs (`outputs/`) are generated artifacts; never commit them.
