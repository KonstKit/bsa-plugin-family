---
name: c4-plantuml-from-context
description: Generate C4 model diagrams as PlantUML/C4-PlantUML source from architecture notes, codebase context, ADRs, tickets, screenshots, whiteboards, and existing `.puml` files. Use when Codex needs to infer a system context, container, component, dynamic, deployment, or system landscape diagram; ask clarifying questions; produce a new `.puml` file; or review/fix an existing C4-PlantUML diagram for scope, abstraction level, syntax, and readability.
---

# C4 PlantUML From Context

Model architecture as C4 first and PlantUML second. Extract the system in scope, audience, abstraction level, boundaries, relationships, runtime scenarios, and deployment environments from the provided context, then encode only that evidence in valid C4-PlantUML.

## Workflow

1. Inventory the evidence.
- Read only the artifacts relevant to the requested architecture view.
- Build a working map of:
  - system in scope
  - intended audience
  - requested or implied diagram type
  - people and external systems
  - internal containers
  - component candidates inside one container
  - runtime scenarios
  - deployment environments and nodes
  - relationships, protocols, and technologies
  - unresolved gaps
- If an existing `.puml` file is provided, treat its aliases, tags, and layout intent as the baseline to preserve.
- If the context clearly needs multiple C4 levels, plan a small diagram set instead of cramming everything into one view.

2. Ask clarifying questions proactively.
- Before writing PlantUML, ask only the blocking questions unless the sources already resolve the ambiguity.
- When the request is highly ambiguous, this is usually 3-7 focused questions; otherwise continue with explicit assumptions.
- Prioritize only questions that change the structure or level of the diagram:
  - what is the single system in scope
  - which C4 view is needed: system context, container, component, dynamic, deployment, or system landscape
  - who is the audience
  - AS-IS vs TO-BE
  - if component: which container should be decomposed
  - if deployment: which environment should be shown
  - which protocols or technologies must be explicit
  - whether one diagram or a set of related diagrams is required
  - desired level of detail and output file path
- Ask short, concrete questions.
- If the user does not answer, continue only with explicit assumptions.
- If the requested architecture is broad, confirm the intended scope before generating files.

3. Choose the C4 view before coding.
- Model the smallest C4 diagram that answers the user's question.
- Use:
  - `System Context` for one software system plus people and external systems around it
  - `Container` for internal applications, data stores, and queues inside one software system
  - `Component` for components inside one container only
  - `Dynamic` for one runtime scenario or use case across existing static elements
  - `Deployment` for one deployment environment with nodes and instances
  - `System Landscape` for portfolio or ecosystem views without a single central system
- Do not mix abstraction levels in one diagram.
- If the user asks for an "architecture overview" and nothing else, start with `System Context` or a `System Context + Container` pair.
- If a diagram is projected to exceed roughly 20-25 primary elements, split it into multiple views or levels.

4. Model with C4 discipline.
- Keep one clear scope per diagram.
- Make every element identifiable by type, name, and short responsibility description.
- Specify technology for every container and component whenever known.
- Label every relationship with an action-oriented phrase that matches the arrow direction.
- Label inter-container relationships with protocol or technology when known.
- Prefer role/persona names for people over individual names unless the individual matters architecturally.
- Use boundaries deliberately to show ownership and scope, not as decoration.
- Keep system context diagrams technology-light.
- Keep component diagrams anchored to one container.
- Keep dynamic diagrams tied to one scenario and one stable static model.
- Keep deployment diagrams tied to one environment at a time unless the user explicitly wants comparison.
- Do not invent undocumented services, components, queues, protocols, or deployment nodes.
- Distinguish evidenced structure from assumed structure.

5. Encode with C4-PlantUML.
- Use the include that matches the diagram type:
  - `C4_Context.puml`
  - `C4_Container.puml`
  - `C4_Component.puml`
  - `C4_Dynamic.puml`
  - `C4_Deployment.puml`
- Prefer the standard library include form `!include <C4/...>` when the environment supports it.
- Fall back to the raw GitHub include only when necessary or explicitly preferred.
- Prefer keyword arguments such as `$techn=`, `$descr=`, and `$tags=` when optional arguments would become ambiguous.
- Use `LAYOUT_LEFT_RIGHT()`, `LAYOUT_TOP_DOWN()`, or `LAYOUT_LANDSCAPE()` only to improve readability.
- Use `LAYOUT_WITH_LEGEND()` for default legend placement.
- Use `SHOW_LEGEND()` only when you need explicit legend control or custom tag entries; keep it as the last line inside the diagram.
- Use custom tags only when they encode stable meaning, not cosmetic variation.
- Keep aliases stable and descriptive.

6. Produce the deliverable.
- Write real `.puml` source, not pseudo-PlantUML.
- Include a title that states the diagram type and scope.
- Emit one focused diagram per file by default.
- If the user explicitly wants multiple diagrams in one file, separate them with distinct `@startuml` / `@enduml` blocks and clear titles.
- Run [scripts/validate_c4_plantuml.py](scripts/validate_c4_plantuml.py) against every generated `.puml` before delivery.
- Treat that validator as opinionated house-style lint plus optional external syntax checking, not as a pure upstream parser oracle.
- Use `--plantuml on` when `plantuml` is installed to add `plantuml -checkonly` on top of the built-in C4 lint rules.
- In CI or any release gate, make the external `plantuml -checkonly` step mandatory whenever the binary is available; the built-in validator is not enough to certify syntax.
- If the diagram is intentionally partial and some lint rules are not desired, disable them explicitly with validator flags instead of silently skipping validation.
- Report assumptions, unresolved questions, and the output file path.
- If validation tooling is unavailable, say so instead of implying that rendering was checked.

7. Review and fix mode.
- Follow this order:
  1. load the existing `.puml` and identify the current C4 level and include
  2. compare the current diagram against the source context
  3. build a gap list: wrong abstraction level, scope drift, missing relationships, missing descriptions or technology, syntax issues, layout issues
  4. describe the intended changes briefly before editing if the gaps are structural
  5. apply the smallest change that resolves the gap
  6. preserve aliases, tags, and style choices when they are still valid
  7. rerun [scripts/validate_c4_plantuml.py](scripts/validate_c4_plantuml.py) and add `--plantuml on` if PlantUML is available
- Prioritize:
  - wrong abstraction level
  - wrong or unclear scope
  - unlabeled or misleading relationships
  - missing technology on containers/components
  - broken syntax
  - legend/title problems
  - avoidable layout churn

## Integration Contract

This skill is a **derived-only, non-canonical** BSA sidecar. When invoked as part of a BSA pipeline run, every generated diagram must trace back to canonical claim-layer anchors via `analysis/views/c4/anchor_manifest.json`. See `skills/bsa-orchestrator/references/sidecar-integration.md` for the orchestrator-owned rules; this skill adds the C4-specific details.

- **Operating modes.** Two modes are supported:
  - **Orchestrated** — invoked by `bsa-orchestrator` as a derived view aid. `anchor_manifest.json` MUST be produced alongside every emitted `.puml`; absence fails `ART-VAL-001-07`.
  - **Standalone** — invoked directly by a user outside of a BSA pipeline (no `analysis/canonical/` in scope). The anchor manifest is skipped by default; the emitted `.puml` is informational only and carries no BSA governance weight.
- **Required path (orchestrated mode).** `analysis/views/c4/anchor_manifest.json` — one manifest per C4 view directory. Adjacent `.puml` files reference manifest entries by `view_element_id`.
- **Anchor mapping rule.** Every `view_element_id` in the PlantUML source — covering the full C4-PlantUML macro taxonomy (`Person`/`Person_Ext`, `System`/`SystemDb`/`SystemQueue` and `_Ext` variants, `Container`/`ContainerDb`/`ContainerQueue` and `_Ext` variants, `Component`/`ComponentDb`/`ComponentQueue` and `_Ext` variants, `Boundary`/`Enterprise_Boundary`/`System_Boundary`/`Container_Boundary`, `Deployment_Node`/`Node` and `_L`/`_R` layout variants, and relationships `Rel`/`BiRel`/`RelIndex`) — MUST map to a canonical `A61.AnchorID` in the manifest. Directional relationship variants (`Rel_U`, `BiRel_Left`, etc.) collapse to their base kind in the manifest. Unmapped view elements are treated as fabrications.
- **Non-canonical status.** The generated `.puml` is never promoted into `analysis/canonical/`. If the diagram surfaces a boundary or component that does not exist in the canonical claim-layer, that is a finding — route it through `A51` rather than editing the diagram to match.
- **Detection heuristic.** If a `.puml` file is generated inside any path containing `analysis/` but no `anchor_manifest.json` is adjacent, the skill refuses to emit — it either asks for the missing manifest (orchestrated intent) or requires an explicit `--standalone` confirmation (standalone intent).

See [references/integration-contract.md](references/integration-contract.md) for the manifest schema, mode-detection rules, and failure modes.

## References

- Read [references/integration-contract.md](references/integration-contract.md) for orchestrated-vs-standalone mode rules, `anchor_manifest.json` schema, and BSA governance linkage.
- Read [references/intake-and-questions.md](references/intake-and-questions.md) when the source material is incomplete, conflicting, or underspecified.
- Read [references/c4-modeling-conventions.md](references/c4-modeling-conventions.md) for C4 view selection, abstraction control, naming, and review criteria.
- Read [references/c4-plantuml-syntax.md](references/c4-plantuml-syntax.md) for the correct C4-PlantUML include matrix, macro syntax, layout rules, and minimal templates.
- Read [references/review-mode.md](references/review-mode.md) when editing an existing C4-PlantUML diagram.
- Run [scripts/test_validate_c4_plantuml.py](scripts/test_validate_c4_plantuml.py) when changing the validator or the fixture set.
- When packaging or archiving the skill, exclude generated cache and sidecar artifacts such as `__pycache__`, `.pyc`, `._*`, and `__MACOSX`.

## Output Contract

- Deliver a `.puml` file or an in-message PlantUML code block if the user asked for inline code only.
- State whether `scripts/validate_c4_plantuml.py` was run and whether `plantuml -checkonly` actually ran or was skipped.
- Keep a short assumption block in the final response.
- Distinguish evidenced structure from assumed structure.
- If the request implicitly needs several C4 levels, say so and either confirm the split or provide the smallest sensible diagram set.
- Do not overclaim completeness: the diagram is a view over the architecture, not the architecture itself.
- If the source remains too ambiguous for safe modeling, stop after the clarifying questions instead of inventing structure.
