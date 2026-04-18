# Intake And Questions

Use this file when the request is ambiguous, broad, or under-specified.

## Working Map

Build a compact working map before drawing anything:

- system in scope
- audience
- requested deliverable
- requested or implied diagram type
- AS-IS vs TO-BE
- people and external systems
- internal containers
- candidate components inside one container
- runtime scenario to show
- deployment environment to show
- protocols and technologies worth labeling
- unresolved gaps

## Question Bank

Ask only questions that change the structure or abstraction level of the result.
Prefer blocking questions only; do not ask filler questions just to reach a count.

### Scope

- What is the single software system in scope?
- Is this diagram about the whole product, one subsystem, or one service?
- Should the output describe the current architecture or the target architecture?

### Diagram Type

- Do you want a system context, container, component, dynamic, deployment, or system landscape diagram?
- If you want a component diagram, which container should be decomposed?
- If you want a deployment diagram, which deployment environment should be shown?
- Do you want one diagram or a small set such as `context + container`?

### Audience And Detail

- Who is the audience: executives, product, engineering, platform, or operations?
- Should the diagram stay high level, detailed, or implementation-leaning?
- Should technologies and protocols be explicit, or should the diagram stay conceptually clean?

### Boundaries And Ownership

- Which systems are external dependencies versus part of the system in scope?
- Which databases, queues, and third-party services matter enough to show explicitly?
- Are there organizational or enterprise boundaries that should be visible?

### Delivery

- Do you want inline PlantUML or a `.puml` file?
- What file path or naming convention should be used?

## Diagram-Type Cues

Use these cues when the user does not name the C4 level explicitly:

- "Big picture", "who uses it", "what does it connect to" -> `System Context`
- "What is inside the platform", "what services/datastores exist" -> `Container`
- "How this service/module is structured internally" -> `Component`
- "Step-by-step request flow", "runtime path", "happy path" -> `Dynamic`
- "AWS/Kubernetes/VMs/nodes/environments" -> `Deployment`
- "Estate overview", "portfolio map", "how these products relate" -> `System Landscape`

## Default Assumptions

If the user does not answer and a safe fallback is needed:

- assume `AS-IS`
- assume one focused diagram unless multiple levels are clearly required
- assume `System Context` for broad architecture overviews
- assume `Container` for internal software structure questions
- assume standard library includes `!include <C4/...>` unless the environment or user prefers raw GitHub URLs
- state every fallback assumption explicitly in the final response
