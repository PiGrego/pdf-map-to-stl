# Repository instructions

- Analyze before modifying files. Keep changes small and focused.
- Do not commit, push, merge, tag, delete branches or rewrite Git history unless the
  user asks for it explicitly.
- Never modify files outside the workspace. Never overwrite files under `samples/`.
- Run `pytest` after behavioural changes; keep `ruff check src tests` clean.
- Goal: tactile maps for blind and visually impaired readers. Judge changes by whether the
  printed plate can be read by touch; keep the tactile check (`tactile_check.py`) meaningful.
- Architecture is vector-native: geometry comes only from PDF vector paths.
  Rasterization is allowed only for validation and previews, never to build geometry.
- Symbol recognition is data-driven: change `config/*.toml` rules, not code, to adapt
  to a new map.
- Outputs (`outputs/`) are generated artifacts; never commit them.
- Every automatic decision is a setting with a default (`config/default.toml`,
  documented in `docs/SETTINGS.md`); add new behaviour the same way, never hard-coded.
