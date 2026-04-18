# Review Mode

Use this workflow when the task is to review, fix, or tighten an existing C4-PlantUML diagram.

## Workflow

1. Load the existing `.puml`.
- Identify the active include: `C4_Context`, `C4_Container`, `C4_Component`, `C4_Dynamic`, or `C4_Deployment`.
- Identify the current diagram title, system in scope, aliases, boundaries, tags, and layout strategy.

2. Reconstruct the current intent.
- Determine which C4 level the file is trying to represent.
- Determine whether the file is AS-IS or TO-BE.
- Determine whether there are multiple views in one file.

3. Compare against the source context.
- Build a gap list before editing:
  - wrong abstraction level
  - wrong system in scope
  - missing or extra elements
  - missing descriptions or technology
  - unlabeled or misleading relationships
  - external/internal confusion
  - broken legend or title
  - syntax or include problems
  - layout problems that obscure meaning

4. Decide the smallest safe change.
- Preserve aliases whenever possible to reduce churn.
- Preserve tags and styling when they still communicate useful meaning.
- If the file is at the wrong C4 level, explain the structural change before editing.
- Split the file only when a single diagram cannot stay readable or methodologically correct.

5. Edit the diagram.
- Fix correctness before aesthetics.
- Prefer relationship and description fixes before layout tweaks.
- Use directional relationship variants only when readability actually improves.
- Keep the diagram readable without narrating it line by line.

6. Validate when possible.
- Always run:
  - `python3 scripts/validate_c4_plantuml.py path/to/file.puml`
- If `plantuml` is available, also run:
  - `python3 scripts/validate_c4_plantuml.py path/to/file.puml --plantuml on`
  - or render with `plantuml -tsvg path/to/file.puml`
- If external PlantUML validation is unavailable, report that explicitly.

## Priorities

Prioritize issues in this order:

- wrong C4 level
- syntax that breaks rendering
- wrong or unclear scope
- missing technology on containers/components
- missing descriptions
- mislabeled relationships
- broken legend/title
- avoidable layout churn

## Delivery

- Summarize the structural fixes briefly.
- Call out any assumptions that remain.
- State whether rendering or syntax validation was actually run.
